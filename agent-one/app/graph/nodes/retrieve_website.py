from app.graph.state import AgentOneState

_MOCK_CHUNKS = [
    {
        "chunk_id": "c1",
        "url": "https://example.com/services",
        "title": "Services",
        "content": (
            "We offer consulting, custom software development, and 24/7 technical support. "
            "Our team specialises in cloud-native architectures and AI-powered solutions."
        ),
    },
    {
        "chunk_id": "c2",
        "url": "https://example.com/pricing",
        "title": "Pricing",
        "content": (
            "Starter plan: $49/month — up to 5 users, core features. "
            "Professional plan: $149/month — up to 25 users, priority support. "
            "Enterprise: custom pricing with SLA guarantees."
        ),
    },
    {
        "chunk_id": "c3",
        "url": "https://example.com/refund-policy",
        "title": "Refund Policy",
        "content": (
            "We offer a 30-day money-back guarantee on all plans. "
            "Refunds are processed within 5-7 business days to the original payment method."
        ),
    },
]


def retrieve_website(state: AgentOneState) -> AgentOneState:
    return {**state, "retrieved_chunks": _MOCK_CHUNKS}
