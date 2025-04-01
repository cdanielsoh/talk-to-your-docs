#!/usr/bin/env python3
import os

import aws_cdk as cdk

from document_chatbot_cdk.bedrock_chatbot_cdk_stack import BedrockChatbotStack
from document_chatbot_cdk.knowledge_base_stack import KnowledgebaseStack


app = cdk.App()

# Create the knowledge base stack first
kb_stack = KnowledgebaseStack(app, "KnowledgebaseStack")

# Create the chatbot stack that depends on the knowledge base stack
chatbot_stack = BedrockChatbotStack(
    app,
    "BedrockChatbotStack",
    kb_id=kb_stack.outputs["knowledgebase_id"],
    kb_document_url=kb_stack.outputs["document_cloudfront_url"]  # Pass this through
)

# Add dependency to ensure proper deployment order
chatbot_stack.add_dependency(kb_stack)

app.synth()
