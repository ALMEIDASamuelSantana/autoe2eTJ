import os
import boto3
from dotenv import load_dotenv

# Carrega as variáveis do .env antes de instanciar os modelos
load_dotenv()

from langchain_core.messages import SystemMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_anthropic import ChatAnthropic
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_community.callbacks import get_openai_callback
from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings

from autoe2e.utils import logger
from .utils import log_user_messages


def create_model_chain(model):
    def invoke_model_chain(system_prompt, user_messages):
        logger.info('Prompt:')
        log_user_messages(user_messages.content)
        
        prompt = ChatPromptTemplate.from_messages([
            SystemMessage(content=system_prompt),
            user_messages
        ])
        output_parser = StrOutputParser()
        chain = prompt | model | output_parser
        
        if model.__class__.__name__ == "ChatOpenAI":
            with get_openai_callback() as cb:
                res = chain.invoke({})
                logger.info("Response:")
                logger.info(res)
                logger.info(cb)
                logger.info("")
                return res
        
        res = chain.invoke({})
        logger.info("Response:")
        logger.info(res)
        logger.info("")
        return res

    return invoke_model_chain


if os.getenv("AUTOE2E_LLM_PROVIDER", "").lower() == "google":
    gemini_flash = ChatGoogleGenerativeAI(
        model=os.getenv("AUTOE2E_GEMINI_MODEL", "gemini-3.1-flash-lite"),
        temperature=0
    )
    gemini_embeddings = GoogleGenerativeAIEmbeddings(model="models/gemini-embedding-001")
    primary_chain = create_model_chain(gemini_flash)
    gemini_chain = primary_chain
    gpt4o = gpt35 = sonnet = haiku = gemini_flash
    gpt4o_chain = gpt35_chain = sonnet_chain = haiku_chain = primary_chain
    openai_embeddings = gemini_embeddings
elif os.getenv("ANTHROPIC_API_KEY"):
    sonnet = ChatAnthropic(model="claude-3-5-sonnet-20240620", max_tokens=1024, temperature=0)
    haiku = ChatAnthropic(model="claude-3-haiku-20240307", max_tokens=1024, temperature=0)
    openai_embeddings = OpenAIEmbeddings(model="text-embedding-3-large")
    primary_model = sonnet
    primary_chain = create_model_chain(primary_model)
    gemini_chain = primary_chain
    gpt4o = ChatOpenAI(model="gpt-4o", max_tokens=256, temperature=0)
    gpt35 = ChatOpenAI(model="gpt-3.5-turbo", max_tokens=256, temperature=0)
    gpt4o_chain = create_model_chain(gpt4o)
    gpt35_chain = create_model_chain(gpt35)
    sonnet_chain = primary_chain
    haiku_chain = create_model_chain(haiku)
elif os.getenv("OPENAI_API_KEY"):
    gpt4o = ChatOpenAI(model="gpt-4o", max_tokens=256, temperature=0)
    gpt35 = ChatOpenAI(model="gpt-3.5-turbo", max_tokens=256, temperature=0)
    sonnet = gpt4o
    haiku = gpt4o
    openai_embeddings = OpenAIEmbeddings(model="text-embedding-3-large")
    primary_chain = create_model_chain(gpt4o)
    gemini_chain = primary_chain
    gpt4o_chain = primary_chain
    gpt35_chain = create_model_chain(gpt35)
    sonnet_chain = primary_chain
    haiku_chain = primary_chain
else:
    gemini_flash = ChatGoogleGenerativeAI(
        model=os.getenv("AUTOE2E_GEMINI_MODEL", "gemini-3.1-flash-lite"),
        temperature=0
    )
    gemini_embeddings = GoogleGenerativeAIEmbeddings(model="models/gemini-embedding-001")
    gpt4o = ChatOpenAI(model="gpt-4o", max_tokens=256, temperature=0)
    gpt35 = ChatOpenAI(model="gpt-3.5-turbo", max_tokens=256, temperature=0)
    sonnet = ChatAnthropic(model="claude-3-5-sonnet-20240620", max_tokens=1024, temperature=0)
    haiku = ChatAnthropic(model="claude-3-haiku-20240307", max_tokens=1024, temperature=0)
    primary_chain = create_model_chain(gemini_flash)
    gemini_chain = primary_chain
    gpt4o_chain = create_model_chain(gpt4o)
    gpt35_chain = create_model_chain(gpt35)
    sonnet_chain = primary_chain
    haiku_chain = primary_chain
    openai_embeddings = gemini_embeddings
