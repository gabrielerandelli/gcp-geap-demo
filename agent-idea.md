Use agents-cli to build an agent capable to perform the four foundamental math operations: add, sub, multiply, division. In order to accomplish this, the agent relies on an MCP server for math operations. You need to build up both the agent the MCP server. 

MCP Server requirements:
- Goal: the tool is in charge of providing the four basic math operations: add, sub, multiply, division
- The MCP server must be implemented via FastMCP
- The MCP server must be deployed both locally and on Cloud Run
- The MCP server accepts authentication via service accounts
- The MCP server must be registered in the Agent Registry of the Gemini Enterprise Agent Platform. Ensure to use the Registry in the Agent Platform, NOT the GE App registry. Details how to build this up: https://docs.cloud.google.com/agent-registry/register-mcp-servers#register-external-servers

Agent requirements:
- Goal: the agent is in charge of interacting with the user to execute math operations
- The agent uses the aforementioned mcp server to execute the operations
- The agent must be an A2A agent
- The agent must be registered in the Agent Registry of the Gemini Enterprise Agent Platform
- The agent will need OpenTelemetry logging up
- The agent must be deployed both locally and on the Agent Runtime
- The agent must be integrated with Model Armor to prevent prompt injection and hate/violence requests
- The agent identity is a service account that is used to authenticate with the MCP server

You also need to create Model Armor templates, if necessary, as well as any other Cloud resource if you cannot do it by yourself.

There's a set of libraries in ADK SDK to implement this. If you have doubts, ask me for clarification. If you cannot find tools or skills to properly implement this, pause and tell me what's the problem. Plan before execute and show me what you are going to do step by step.

