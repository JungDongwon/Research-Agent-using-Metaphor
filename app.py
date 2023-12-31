# Adapted from the Chainlit Cookbook: https://github.com/Chainlit/cookbook/tree/main/openai-functions-streaming

import openai
import json
import ast
import os
import chainlit as cl
from function_schemas import FUNCTIONS_SCHEMA
from functions import Functions

openai.api_key = os.environ.get("OPENAI_API_KEY")

MAX_ITER = 5

FUNCTIONS_MAPPING = {
    "search_papers": Functions.search_papers,
    "recommend_similar_resources": Functions.recommend_similar_resources,
    "get_detailed_information": Functions.get_detailed_information
}

async def process_new_delta(new_delta, openai_message, content_ui_message, function_ui_message):
    if "role" in new_delta:
        openai_message["role"] = new_delta["role"]
    if "content" in new_delta:
        new_content = new_delta.get("content") or ""
        openai_message["content"] += new_content
        await content_ui_message.stream_token(new_content)
    if "function_call" in new_delta:
        if "name" in new_delta["function_call"]:
            openai_message["function_call"] = {
                "name": new_delta["function_call"]["name"]}
            await content_ui_message.send()
            function_ui_message = cl.Message(
                author=new_delta["function_call"]["name"],
                content="", indent=1, language="json")
            await function_ui_message.stream_token(new_delta["function_call"]["name"])

        if "arguments" in new_delta["function_call"]:
            if "arguments" not in openai_message["function_call"]:
                openai_message["function_call"]["arguments"] = ""
            openai_message["function_call"]["arguments"] += new_delta["function_call"]["arguments"]
            await function_ui_message.stream_token(new_delta["function_call"]["arguments"])
    return openai_message, content_ui_message, function_ui_message

async def send_response(function_name, function_response):
    await cl.Message(
        author=function_name,
        content=str(function_response),
        language="json",
        indent=1,
    ).send()

async def process_function_call(function_name, arguments, message_history):
    if function_name in FUNCTIONS_MAPPING:
        function_response = FUNCTIONS_MAPPING[function_name](**arguments)
        message_history.append(
            {
                "role": "function",
                "name": function_name,
                "content": function_response,
            }
        )
        await send_response(function_name, function_response)
    else:
        print(f"Unknown function: {function_name}")

@cl.on_chat_start
def start_chat():
    cl.user_session.set(
        "message_history",
        [{"role": "system", "content": "You are a helpful assistant who helps users with conducting research. You can give useful advices to the user when user asks about academic or technical subjects. Also you can propose some promising research directions."}],
    )


@cl.on_message
async def run_conversation(user_message: str):
    message_history = cl.user_session.get("message_history")
    message_history.append({"role": "user", "content": user_message})

    cur_iter = 0

    while cur_iter < MAX_ITER:

        # OpenAI call
        openai_message = {"role": "", "content": ""}
        function_ui_message = None
        content_ui_message = cl.Message(content="")
        async for stream_resp in await openai.ChatCompletion.acreate(
            model="gpt-3.5-turbo-0613",
            messages=message_history,
            stream=True,
            function_call="auto",
            functions=FUNCTIONS_SCHEMA,
            temperature=0
        ):

            new_delta = stream_resp.choices[0]["delta"]
            openai_message, content_ui_message, function_ui_message = await process_new_delta(
                new_delta, openai_message, content_ui_message, function_ui_message)

        message_history.append(openai_message)
        if function_ui_message is not None:
            await function_ui_message.send()

        if stream_resp.choices[0]["finish_reason"] == "stop":
            break

        elif stream_resp.choices[0]["finish_reason"] != "function_call":
            raise ValueError(stream_resp.choices[0]["finish_reason"])

        # if code arrives here, it means there is a function call
        function_name = openai_message.get("function_call").get("name")
        arguments = ast.literal_eval(
            openai_message.get("function_call").get("arguments"))

        await process_function_call(function_name, arguments, message_history)
        cur_iter += 1
