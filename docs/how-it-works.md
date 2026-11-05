# How cria works

[← Features](features.md) · [Explore](README.md) · [How we evaluate it →](methodology.md)

A **coding harness** is the application you talk to: it manages the session and runs tools. cria sits between it and the model server.

![The harness sends model requests through cria; commands run through the harness](media/execution-boundary.svg)

## A typical turn

```mermaid
sequenceDiagram
    participant H as Coding harness
    participant C as cria
    participant M as Model server
    H->>C: Task, conversation and available tools
    C->>M: Prepared request
    M-->>C: Reply or proposed tool call
    C-->>H: Reply or supported tool-call repair
    H->>H: Run permitted tool
    H->>C: Tool result
    C->>M: Prepared request with result
```

The model does the coding. cria prepares context and can repair a supported malformed call on its way back. The harness executes the call and returns the result.

## When a check is needed

```mermaid
flowchart LR
    A[Work in progress] --> B{Review needed?}
    B -- Yes --> C[Harness runs checks requested by cria]
    C --> D[Actual output and workspace facts]
    D --> E[Reasoned review]
    E -- More work --> A
    E -- Supported completion --> F[Return to harness]
    E -. Bounded unverified exit .-> F
    B -- No, keep working --> A
```

This is a simplified path: checks depend on the task, available tools and configuration. A failed or incomplete check is not a clean result. Two bounded exits can return without verification: when neither a reasoner nor shell is available, or when the completion-check limit is reached. cria can also review proposed edits and steer a stuck session before a completion claim.

## Different jobs, different roles

A **coder** writes; a **reasoner** weighs evidence; a **classifier** answers narrow routing questions; a **compactor** helps manage long history. They can share one model server or use separate backends. The optional planner is off unless explicitly enabled.

For the detailed contracts, see [architecture](shephard.md), [design principles](principles.md), and [completion evidence](participation-evidence.md).
