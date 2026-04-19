from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, replace
from typing import Callable

from masfactory.adapters.context import ContextComposer, ContextQuery
from masfactory.adapters.context.provider import HistoryProvider
from masfactory.adapters.memory import Memory
from masfactory.adapters.retrieval import Retrieval
from masfactory.adapters.tool_adapter import ToolAdapter
from masfactory.core.message import MessageFormatter


@dataclass(frozen=True)
class RequestContext:
    system_prompt: str
    user_prompt: str
    user_payload: dict
    user_message_content: object
    messages: list[dict]
    history_messages: list[dict]
    selected_provider_blocks: list[tuple[str, list[object]]]
    tool_adapter: ToolAdapter | None
    context_query: ContextQuery | None
    active_context_providers: list[object]
    active_context_provider_map: dict[str, object]
    active_context_source_entries: list[dict]
    active_context_source_aliases: dict[str, list[str]]


class RequestAssembler:
    """Assemble one Agent request while keeping semantic layers separate."""

    def __init__(
        self,
        *,
        name: str,
        formatter: MessageFormatter,
        output_keys_prompt_factory: Callable[[], dict],
        context_query_builder: Callable[[dict[str, object], dict], str],
        memories: list[Memory],
        history_memories: list[HistoryProvider],
        retrievers: list[Retrieval],
        user_tools: list[Callable],
        context_tool_renderer,
        user_payload_factory: Callable[[], dict],
        user_payload_builder: Callable[[list[dict], list[tuple[str, list[object]]], dict[str, object]], dict] | None = None,
        system_message_builder: Callable[[str], object] | None = None,
        user_message_builder: Callable[[str], object] | None = None,
    ):
        self._name = name
        self._formatter = formatter
        self._output_keys_prompt_factory = output_keys_prompt_factory
        self._context_query_builder = context_query_builder
        self._memories = memories
        self._history_memories = history_memories
        self._retrievers = retrievers
        self._user_tools = user_tools
        self._context_tool_renderer = context_tool_renderer
        self._user_payload_factory = user_payload_factory
        self._user_payload_builder = user_payload_builder
        self._system_message_builder = system_message_builder
        self._user_message_builder = user_message_builder

    def assemble(
        self,
        *,
        system_payload: str | dict,
        context_knowledges: dict[str, object],
        attributes_store: dict[str, object],
        input_dict: dict[str, object],
    ) -> RequestContext:
        system_prompt = self._formatter.dump(system_payload)

        initial_user_payload = dict(self._user_payload_factory())

        query_text = self._context_query_builder(input_dict, initial_user_payload)
        base_query = ContextQuery(
            query_text=query_text,
            inputs=context_knowledges,
            attributes=attributes_store,
            node_name=self._name,
        )

        def _is_passive_provider(provider: object) -> bool:
            if not getattr(provider, "supports_passive", True):
                return False
            return bool(getattr(provider, "passive", True))

        def _is_active_provider(provider: object) -> bool:
            if not getattr(provider, "supports_active", True):
                return False
            return bool(getattr(provider, "active", False))

        all_providers = [*self._memories, *self._retrievers]
        passive_providers = [p for p in all_providers if _is_passive_provider(p)]
        active_providers = [p for p in all_providers if _is_active_provider(p)]

        composer = ContextComposer(providers=passive_providers, history_providers=[*self._history_memories])
        history_messages = composer.get_history_messages(base_query, top_k=-1)
        query = ContextQuery(
            query_text=query_text,
            inputs=context_knowledges,
            attributes=attributes_store,
            node_name=self._name,
            messages=history_messages,
        )
        provider_blocks = composer.collect_provider_blocks(query, top_k=8)
        selected_provider_blocks = composer.policy.select(provider_blocks, top_k=8)

        if self._user_payload_builder is not None:
            user_payload = dict(self._user_payload_builder(history_messages, selected_provider_blocks, input_dict))
        else:
            user_payload = initial_user_payload
        user_payload = composer.renderer.inject(user_payload, selected_provider_blocks)

        base_labels: list[str] = []
        for provider in active_providers:
            label = getattr(provider, "context_label", provider.__class__.__name__)
            if not isinstance(label, str) or not label.strip():
                label = provider.__class__.__name__
            base_labels.append(label)

        counts = Counter(base_labels)
        seq: defaultdict[str, int] = defaultdict(int)
        source_entries: list[tuple[str, str, object]] = []
        for provider, base_label in zip(active_providers, base_labels):
            if counts[base_label] == 1:
                source_name = base_label
            else:
                seq[base_label] += 1
                source_name = f"{base_label}#{seq[base_label]}"
            source_entries.append((source_name, base_label, provider))

        active_context_provider_map = {name: provider for name, _label, provider in source_entries}
        active_context_source_aliases = {
            base_label: [name for name, label, _provider in source_entries if label == base_label]
            for base_label, count in counts.items()
            if count > 1
        }
        active_context_source_entries = [
            {"name": name, "label": base_label, "type": provider.__class__.__name__}
            for name, base_label, provider in source_entries
        ]

        tools: list[Callable] = list(self._user_tools)
        if active_providers:
            existing_names = {tool.__name__ for tool in tools}

            list_tool_name = "list_context_sources"
            retrieve_tool_name = "retrieve_context"
            if list_tool_name in existing_names:
                list_tool_name = "masfactory_list_context_sources"
            if retrieve_tool_name in existing_names:
                retrieve_tool_name = "masfactory_retrieve_context"

            def list_context_sources() -> dict:
                """List available active context sources for tool-call retrieval."""
                return {"sources": list(active_context_source_entries)}

            list_context_sources.__name__ = list_tool_name

            def retrieve_context(source: str, query_text: str, top_k: int = 8) -> dict:
                """Retrieve context blocks from a named active source."""
                provider = active_context_provider_map.get(source)
                if provider is None:
                    aliases = active_context_source_aliases.get(source)
                    if aliases:
                        raise ValueError(
                            f"Ambiguous context source: {source}. "
                            f"Choose one of: {aliases} (call list_context_sources first)."
                        )
                    raise ValueError(
                        f"Unknown context source: {source}. "
                        f"Available: {sorted(active_context_provider_map.keys())}"
                    )

                effective_query = replace(query, query_text=(query_text or query.query_text))
                blocks = provider.get_blocks(effective_query, top_k=int(top_k))  # type: ignore[attr-defined]

                rendered = ""
                injected = self._context_tool_renderer.inject({}, [(source, blocks)]) if blocks else {}
                if injected and "CONTEXT" in injected:
                    rendered = str(injected["CONTEXT"])

                return {
                    "provider": source,
                    "query": effective_query.query_text,
                    "blocks": [asdict(block) for block in blocks],
                    "rendered": rendered,
                }

            retrieve_context.__name__ = retrieve_tool_name
            tools.extend([list_context_sources, retrieve_context])

        tool_adapter = ToolAdapter(tools) if tools else None
        user_prompt = self._formatter.dump(user_payload)
        system_message_content = self._system_message_builder(system_prompt) if self._system_message_builder else system_prompt
        user_message_content = self._user_message_builder(user_prompt) if self._user_message_builder else user_prompt
        messages = [
            {"role": "system", "content": system_message_content},
            *history_messages,
            {"role": "user", "content": user_message_content},
        ]

        return RequestContext(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            user_payload=user_payload,
            user_message_content=user_message_content,
            messages=messages,
            history_messages=history_messages,
            selected_provider_blocks=selected_provider_blocks,
            tool_adapter=tool_adapter,
            context_query=query,
            active_context_providers=active_providers,
            active_context_provider_map=active_context_provider_map,
            active_context_source_entries=active_context_source_entries,
            active_context_source_aliases=active_context_source_aliases,
        )
