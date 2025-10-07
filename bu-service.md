
Goal:
Build a service that i can deploy to railway in a new repo called llm-use.
This should be called from our library so that we can wrap models to make money with them.

Moat:
- faster: in the new service we remove structured output and parse the response with unstructured_parser.py - this speed things up ()
- we know exactly what prompts/models work best for browser automation
- maybe cheaper (less input tokens)
- dont tell users which model we - use 
- black box charge 0.5$/ 1m tokens (gemini +20%)


1. UX from local library:

```python
from browser_use import Agent, ChatBrowserUse

agent = Agent(
    task="Find the number of stars of the browser-use repo",
    llm=ChatBrowserUse(super_fast=True),
)
```



2. ChatBrowserUse inside OpenSource:
This wraps BaseChatModel and sends it to the browser-use cloud api.

class ChatBrowserUse(BaseChatModel):
    super_fast = True
    provider = "browser-use"

    async def ainvoke(
            self, messages: list[BaseMessage], output_format: type[T] | None = None
        ) -> ChatInvokeCompletion[T] | ChatInvokeCompletion[str]:

        # send both to browser-use cloud api with env key from .env
        # send to fastapi endpoint
        # gets json response
        return ChatInvokeCompletion(completion=json response)

    


3. browser-use cloud api (users dont see this ): 
This is in a seperate folder which i can deploy to railway.

This has one file with the  ChatBrowserUseCloud class.
This just gets the ainvoke, removes the structured output, but adds to the system prompt the tools.
with something like get_prompt_description either pass that in or get this yourself from the output_model.

then send it to ChatGoogle important from browser-use library.
If super_fast choose model gemini-flash-lite-latest.
If not super_fast choose model gemini-flash-latest.

have a dummy method to verify the api key. in the beginning just 12345678. (give me 10000 credits default can be dummy)

then before the llm call detuct 1ct in credits. if not enough credits throw an error. 

then do the llm call with real aivoke with chatgoogle without outputfomat and updated messages. 
this uses my organizations gemini key in railway.


then parse the output with unstructured_parser.py which is only in the special repo.
remove unstructured_parser.py from the browser-use library.

then calculate the cost, do +1ct and - the cost with some hard coded variables with cost per token. 
0.5$/ 1m tokens input, 2$/ 1m tokens output and 0.1$/ 1m tokens cached


then return the parsed json + cost to the user.


```python

from browser_use.llm.base import BaseChatModel
from browser_use.llm.google.chat import ChatGoogle
from browser_use.llm.openai.chat import ChatOpenAI
class ChatBrowserUseCloud(BaseChatModel):
    api_key = 12345678

```


4. wrap fast api service around this. so that i can deploy to railway.




5. make it that i could theoretical just copy paste the new folder into my local library and use ChatBrowserUseCloud directly with my gemini key without fastapi.




earlier implemmentation:
response = await self.get_client().aio.models.generate_content(
    model=self.model,
    contents=contents,  # type: ignore
    config=config,
)

elapsed = time.time() - start_time
self.logger.debug(f'✅ Got unstructured response in {elapsed:.2f}s')

usage = self._get_usage(response)

# Parse the unstructured text response
if response.text:
    try:
        from browser_use.llm.google.unstructured_parser import UnstructuredOutputParser

        self.logger.debug(f'📄 Raw model response:\n{response.text}')
        parsed_dict = UnstructuredOutputParser.parse(response.text, output_format)
        return ChatInvokeCompletion(
            completion=output_format.model_validate(parsed_dict),
            usage=usage,
        )