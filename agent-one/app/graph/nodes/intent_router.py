from langchain_openai import ChatOpenAI
from app.graph.state import AgentOneState

_SYSTEM = """You are an intent classifier. Given a user message, classify it into exactly one of these categories:
- website_qa: questions about website content, services, policies, pricing, company info, refunds, etc.
- sql_qa: questions about specific user data, orders, account status, invoices, etc.
- hybrid: questions that require both website content and user-specific data
- clarification: ambiguous questions that need more context
- unsupported: off-topic questions unrelated to the business

Reply with ONLY the category name, nothing else."""


def route_intent(state: AgentOneState) -> AgentOneState:
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
    message = state["user_message"]
    response = llm.invoke([
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": message},
    ])
    intent = response.content.strip().lower()
    return {**state, "intent": intent}
