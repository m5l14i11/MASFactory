# Basic Components

Components are the building blocks of MASFactory workflows. They include `Node` components, `Edge` components, and `MessageFormatter` components.
- `Node`: the abstract computation unit on a `Graph`; `Graph`, `Agent`, control components, and others are all derived from `Node`
- `Edge`: connects two nodes for flow control and automatic message forwarding
- `MessageFormatter`: defines how model output is parsed into a `dict`, and how a `dict` is rendered back into prompt text

::: tip Node Components
`Node` components do not appear directly in MASFactory workflows, but appear as their derived classes, such as `Graph`, `Agent`, `Switch`, etc. They undertake core functions such as sub-workflows, computation, and control. All components introduced below are `Node` class components.
:::

## Top-level Components:

Top-level components refer to objects that can be directly instantiated and run independently by users. They are the outermost nodes that neither belong to any `Graph` nor serve as `Node` or subgraphs of other `Graph`.
MASFactory provides two types of top-level components: `SingleAgent` and `RootGraph`.

### `RootGraph`
Top-level executable workflow container. Can be directly instantiated by users, serving as a "canvas" to host nodes and edges, organize the overall DAG, and responsible for one-time execution and result output. Main methods:
- Constructor parameters: `name`, `attributes`? <br>
  Where `name` is the name of RootGraph; `attributes` are node variables of RootGraph, accessible to all subgraphs and nodes.
::: tip Node Variables
For detailed introduction to `node variables`, please refer to: [Concepts-Node Variables](/guide/concepts#node-variables)
:::
- Related methods:
    ::: tip Method Description
    `RootGraph` is derived from `Graph`, so the methods `create_node`, `create_edge`, `edge_from_entry` and `edge_to_exit` below are actually inherited from `Graph`.<br>
    At the same time, both `RootGraph` and `Graph` are subclasses of `Node`, where the `build` method is declared in `Node` and has different implementations in all its subclasses.
    :::
    - `create_node`: Parameters include `cls`, `*args`, `**kwargs`; returns `Node`.<br>
  Create a node on `RootGraph` (such as `Agent`, `DynamicAgent`, `AgentSwitch`, `LogicSwitch`, `Graph`, `Loop`, `CustomNode`, etc.). Where `cls` must be a `Node` subclass (`SingleAgent` and `RootGraph` are prohibited as intra-graph nodes). Other parameters are passed as-is to the corresponding constructor, returning the node instance.
    - `create_edge`: Parameters include `sender`, `receiver`, `keys`?; returns `Edge`.<br>
  Create a directed edge between two nodes in the current graph. Where `keys` define fields to be passed and their natural language descriptions. Internal validation includes loop and duplicate-edge checking; created edges are automatically registered to both endpoint nodes and graph.
    - `edge_from_entry`: Parameters include `receiver`, `keys`?; returns `Edge`.<br>
  Create a directed edge from graph entry to node `receiver` in the graph.
    - `edge_to_exit`: Parameters include `sender`, `keys`?; returns `Edge`.<br>
  Create a directed edge from node `sender` in the graph to graph exit.
    - `build`: No parameters.<br>
  Recursively build `RootGraph`, its subgraphs, and its nodes. For declarative graphs, this is also where `nodes=[...]` / `edges=[...]` are materialized into real nodes and edges. Must execute this method before calling `invoke`.
    - `invoke`: Parameters include `input`, `attributes`?; returns `(dict, dict)`.<br>
  Start workflow execution. Where `input` format needs to match entry edge `keys`; returns `(output_dict, attributes_dict)`.
::: warning Graph Constraints (recommended practice)
To avoid deadlocks or unexpected early exits at runtime, follow these constraints when possible:<br>
1. Avoid dangling or unreachable nodes whenever possible; the framework does not uniformly reject isolated-node structures during `build()`;<br>
2. When creating edges connected to `entry` and `exit`, you must use `edge_from_entry` or `edge_to_exit`, not `create_edge`;<br>
3. The `receiver` and `sender` passed to `create_edge` must be `Node` objects created by the current graph's `create_node` method;<br>
4. `Node` and `Edge` definitions must not create illegal cycles. If you need loop behavior, use the `Loop` component.
:::
- Example reference: [Create a linear workflow](/examples/sequential_workflow)

### `SingleAgent`
Single agent component. An Agent component that can be used independently without relying on any Graph, users can directly instantiate and use it.<br>
Suitable for quick Q&A, simple tool calls, scripted batch processing and other tasks that do not require complete workflow orchestration.
- Constructor parameters: `name`, `model`, `instructions`, `prompt_template`?, `tools`?, `memories`?, `model_settings`?, `role_name`?, `formatters`?, `skills`?, `attributes`?, `hide_unused_fields`?, `reuse_attachment_tags`? <br>
  Parameter meanings refer to [Agent](#Agent). `SingleAgent` follows the same memory rule: at most one `HistoryProvider`-backed memory may be attached.
- Related methods:
    - `invoke`: Parameters include `input` (`dict`); returns `dict`.<br>
    `SingleAgent` uses `dict` for both input and output (parsed/rendered by the configured `MessageFormatter`).
- Example: [Create a single agent workflow](/examples/agents#SingleAgent)

## Subgraph Components

Subgraph components cannot be directly instantiated by users, but are created through the `create_node` interface of other `Graph` instances. The resulting subgraph objects also have `create_node` and `create_edge` interfaces and can have their own internal `Node`. Subgraphs connect with other `Node` at the same level through the parent graph's `create_edge` interface, thus forming DAG structure.

### `Graph`
Sub-workflow node supporting reuse and nesting.
- Constructor parameters: `name`, `pull_keys`?, `push_keys`?, `attributes`? <br>
    Where `name` is the graph name for identification in logs;<br>
    `pull_keys`, `push_keys` and `attributes` are all node variable control logic. `pull_keys` controls extracting corresponding fields from node variables in parent graph; `push_keys` controls updating corresponding fields in parent graph; `attributes` are node variable fields that this node carries. Related introduction reference: [Concepts-Node Variables](/guide/concepts#node-variables).
- Features: Built-in `Entry`/`Exit`, serving as "stages" that host multiple nodes; inherits `BaseGraph`'s node/edge management and performs baseline checks such as duplicate-edge and illegal-cycle validation during edge creation.
- Related methods: `edge_from_entry`, `edge_to_exit`, `create_node` and `create_edge`, specific introduction reference: [RootGraph](#RootGraph).
- Application scenarios: Divide complex processes into several sub-stages for easy reuse and debugging.

### `Loop`
Loop subgraph, encapsulating iteration control and optional LLM termination judgment functionality.
- Constructor parameters: `name`, `max_iterations`, `model`?, `terminate_condition_prompt`?, `terminate_condition_function`?, `pull_keys`?, `push_keys`?, `attributes`?, `initial_messages`? 
    - `max_iterations`: Controls maximum loop count.
    - `model` and `terminate_condition_prompt`: Used to set up model and logic for using LLM to determine termination conditions.
    - `terminate_condition_function`: Recommended Python termination callback (`True` means terminate).
    - `pull_keys`, `push_keys` and `attributes`: Control node variable logic, detailed reference: [Concepts-Node Variables](/guide/concepts#node-variables).
- Features: Contains an internal `Controller` node that checks `max_iterations` condition and `terminate_condition_prompt` condition at the beginning of each loop; `TerminateNode` supports early exit within loop body.
- Related methods:
    - `create_node` and `create_edge`: Usage same as: [RootGraph](#RootGraph).
	- `edge_from_controller`: Parameters include `receiver`, `keys` etc.; returns `Edge` (start each iteration from controller).
	- `edge_to_controller`: Parameters include `sender`, `keys` etc.; returns `Edge` (result flows back to controller forming next round input).
	- `edge_to_terminate_node`: Parameters include `sender`, `keys` etc.; returns `Edge` (trigger forced termination within loop body).
- Termination conditions: Terminate when reaching `max_iterations` or when LLM determines `terminate_condition_prompt` is satisfied.
- Force exit loop: Immediately exit when `terminate_node` receives any message.
- Example: [Loop example](/examples/looping)
::: warning Loop Constraints
1. `Loop` must form a loop path centered on `Controller`, and no other loops are allowed except this loop.
2. `Controller` only makes loop exit judgment at the beginning of each iteration. If you need to exit the loop midway, please use `TerminateNode` node to exit the loop.
3. Edges connected to `Controller` node and `TerminateNode` node must be created through `edge_from_controller`, `edge_to_controller` and `edge_to_terminate_node` interfaces, cannot be created through `create_edge` interface.
4. When `TerminateNode` receives a message, it will immediately trigger the exit mechanism (equivalent to `break` logic in programming languages to exit loops).
5. The `keys` on `edge_from_controller`, `edge_to_controller`, `edge_to_terminate_node` and `Loop`'s `in_edges` and `out_edges` must be the same to avoid errors.
:::

## Agent Components
### `Agent`
Standard agent node.
- Constructor parameters: `name`, `model`, `instructions`, `prompt_template`?, `formatters`?, `tools`?, `memories`?, `retrievers`?, `pull_keys`?, `push_keys`?, `model_settings`?, `role_name`?, `hide_unused_fields`?, `reuse_attachment_tags`?<br>
    - `name`: Node name for identifying current Agent;<br>
    - `model`: Large model called by Agent, receives a `Model` object, adapted for mainstream LLM APIs. Detailed reference: [Model Adapters](/guide/model_adapter);<br>
    - `instructions`: Instruction information sent to Agent. Receives a string or string list; when it's a list, it will be joined with newline characters into complete instructions. Supports using `{replacement_field}` to embed fields from `in_edges` `keys`, fields from node variables `attributes`, `role_name` into instructions;<br>
    - `prompt_template`: Agent's prompt template (corresponding to user prompt). Supports `str` or `list[str]`; when it's a list, it will be joined with newline characters; can be used in combination with `instructions`; defaults to `None`;<br>
    - `formatters`: Message formatter(s) that define the LLM I/O protocol. Pass a single formatter (used for both in/out) or a list of two formatters `[in, out]`. Defaults to “paragraph-style input + JSON output”.<br>
    - `tools`: List of tool functions available for Agent to call. Function names, parameter names, return value types and docstrings will be automatically added to LLM context by MASFactory, automatically call corresponding tools based on LLM call results, and return results to LLM;<br>
		- `memories`: Memory adapters (write + read). Except for `HistoryMemory`, memories act as context sources via `get_blocks(...)` (injected into `CONTEXT`), and Agents will `insert(...)` after each step. At most one `HistoryProvider`-backed memory may be attached to an Agent; other memory backends are unlimited.<br>
		- `retrievers`: Read-only RAG / external context sources injected via `get_blocks(...)`. MCP sources can also be plugged in here.<br>
		- `model_settings`: Additional normalized model settings passed to the adapter. Supports: `temperature` (float, range [0.0, 2.0]), `top_p` (float, range [0.0, 1.0]), `max_tokens` (positive integer), `stop` (stop words, `str` or `list[str]`). Unlisted keys will be passed as-is to the model adapter (if model supports). Example: `{"temperature": 0.7, "top_p": 0.95, "max_tokens": 512, "stop": ["</end>"]}`;<br>
    - `role_name`: Agent's role name. Can use `{role_name}` to insert it into instructions. If `role_name` is not set, `role_name` directly uses the value of `name`.
    - `hide_unused_fields`: If `True`, input fields not consumed by template placeholders will not be appended into the user payload.
    - `reuse_attachment_tags`: If `True`, same-turn media is deduplicated; when the attached history returns rich media blocks, matching attachments can reuse those existing tags instead of being resent. History-side media indexing/merging remains controlled by the `HistoryMemory` instance, not by `Agent`.
- Features:
  - Model adaptation: Adapts mainstream model API interfaces.
  - Automatic tool calling: When LLM returns tool calls, automatically execute corresponding tools, backfill results and request LLM again until final content is returned.
  - Context injection (RAG/Memory/MCP): Providers emit `ContextBlock`s which are injected into the user payload as a `CONTEXT` field during Observe. Supports passive (auto-inject) and active (on-demand via tools) modes.
  - System instructions and user templates: `instructions` supports `str` or `list` with placeholders (like `{role_name}`, incoming edge `keys`, node variables); can use `prompt_template` to modify input from `in_edges`.
  - Structured output constraints: Automatically generate JSON field constraint prompts based on outgoing edge `output_keys` to guide model strict output.
  - Node variable support: Follows `Node`'s `pull_keys`, `push_keys` and `attributes` rules; `Agent` defaults `pull_keys` and `push_keys` to empty dictionaries.
  
 - Related methods:
   - `build()`: Mark `Agent` as executable (usually called uniformly by `Graph`).
   - `add_memory(memory: Memory)`: Add a memory adapter (used for `get_blocks` injection and step-time `insert`).
   - `add_retriever(retriever: Retrieval)`: Add a retrieval/context source (used for `get_blocks` injection and/or active retrieval tools).
- Example: [Agent example](/examples/agents)
::: tip Deep dive
- Observe/Think/Act runtime: [`/guide/agent_runtime`](/guide/agent_runtime)
- Context adapters (RAG/Memory/MCP): [`/guide/context_adapters`](/guide/context_adapters)
:::

### `DynamicAgent`
Dynamic agent node.<br>
`DynamicAgent` is similar to `Agent`, except its `instructions` are not fixed at coding time. Instead, they are read from input messages at runtime.<br>
At runtime, `DynamicAgent` reads the field named by `instruction_key` (default: `"instructions"`) from the input payload, uses that value to override the instructions for the current execution, then removes that field from the input before continuing.
If the field is absent, `DynamicAgent` falls back to `default_instructions`.
- Constructor parameters: `name`, `model`, `default_instructions`, `instruction_key`?, `prompt_template`?, `tools`?, `memories`?, `retrievers`?, `pull_keys`?, `push_keys`?, `model_settings`?, `role_name`? <br>
  - `default_instructions`: Default instructions used at initialization. In practice, runtime behavior is usually driven by the field referenced by `instruction_key`;<br>
  - `instruction_key`: Key name in the incoming message used to dynamically override instructions. Default is `"instructions"`; if this key exists in the input, its value is used as the instructions for the current execution;<br>
  - `name`, `model`, `tools`, `memories`, `retrievers`, `pull_keys`, `push_keys`, `model_settings`, `prompt_template`: Same as [Agent](#Agent);<br>
- Usage example: [DynamicAgent example](/examples/agents#DynamicAgent)

## Conditional Branch Components

Branch components are similar to if branches in programming languages, deciding the direction of the next path based on current state and conditions. MASFactory provides two branch components: logic branch component `LogicSwitch` based on callback functions and semantic branch component `AgentSwitch` based on Agent semantic judgment.

### `LogicSwitch`
Conditional routing component based on callback functions, using `condition_binding`(callback, out_edge) to bind branch conditions.

- Constructor parameters: `name`, `pull_keys`?, `push_keys`? (meaning same as [`Agent`](#Agent))
- Related methods:
  - `condition_binding(callback, out_edge)`: Bind an `out_edge` with condition callback function.
    - `callback(message, attributes) -> bool`: where `message` is the aggregated message from incoming edges (`dict`), and `attributes` is the node-variable dict. When it returns `True`, the message is forwarded to that `out_edge` and the target node connected by that edge is added to the execution queue.
::: tip LogicSwitch and AgentSwitch
1. `LogicSwitch` will pass the message `message` from `in_edges` and node variables `attributes` inherited from parent graph into callback functions corresponding to all out_edges, and decide whether to put target nodes connected by those `out_edges` into the execution queue based on the return values of callback functions.
2. `LogicSwitch` supports "multi-path matching", that is, if multiple `out_edge` corresponding condition functions return `True`, nodes on these paths are all put into the execution queue.
3. `AgentSwitch` has similar processing logic to `LogicSwitch`. The difference is that `LogicSwitch` uses callback functions for condition judgment, while `AgentSwitch` uses LLM for condition judgment based on condition semantics.
:::
::: warning Situations to Avoid
1. If an `out_edge` is not bound with condition callback function or condition semantics, the target node corresponding to this edge will never be added to the execution queue. This situation should be avoided in development.
2. If all conditions bound to all `out_edge` evaluate to `False` in a certain execution, the switch will close all outgoing edges and forward nothing. If the execution queue becomes empty, the workflow ends early. To avoid surprises, add a **default/fallback branch** (e.g., a predicate that always returns `True`) or handle the “no match” case explicitly.
:::
- Usage example: [Logic branch example](/examples/conditional_branching#logic-branch)

### `AgentSwitch`
LLM-based semantic routing component, using `condition_binding`(prompt, out_edge) to bind routing semantics.

- Constructor parameters: `name`, `model`, `pull_keys`?, `push_keys`? (meaning same as [`Agent`](#Agent))
- Related methods:
  - `condition_binding(prompt, out_edge)`: Bind semantic judgment prompt `prompt` for a certain outgoing edge. `AgentSwitch` will combine incoming edge messages with each outgoing edge's `prompt` one by one, call `model` for judgment (supports multiple outgoing edges hitting simultaneously).
- Usage example: [Semantic branch example](/examples/conditional_branching#semantic-branch)

## Custom Nodes
### `CustomNode`
Node that customizes runtime behavior with a callback function, convenient for integrating external computation or rule-based logic. Supports setting the handler at initialization time or later through `set_forward`.

- Constructor parameters: `name`, `forward`?, `memories`?, `tools`?, `retrievers`?, `pull_keys`?, `push_keys`? <br>
  - `forward`: Custom runtime callback, **must return `dict`**; if `forward` is `None`, this node passes input through as-is (input is also `dict`);<br>
  - `memories`, `tools`, `retrievers`: Available memory / tool / retriever lists for the current node (as optional callback parameters);<br>
  - `pull_keys`, `push_keys`: Same meaning as `Node` (node variables).

- Related methods:
  - `set_forward(forward_callback)`: Set callback function.

- Callback function:
  - Callback parameter forms (automatically matched by parameter count, up to `self`):
    1) `forward(input)`;
    2) `forward(input, attributes)`;
    3) `forward(input, attributes, memories)`;
    4) `forward(input, attributes, memories, tools)`;
    5) `forward(input, attributes, memories, tools, retrievers)`;
    6) `forward(input, attributes, memories, tools, retrievers, self)`;
  - Return value: Callback return value is automatically sent to downstream nodes through all outgoing edges (return type must be `dict`).
- Usage example: [CustomNode example](/examples/custom_node)
