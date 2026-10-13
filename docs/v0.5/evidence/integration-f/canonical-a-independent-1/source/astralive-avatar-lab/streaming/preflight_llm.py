"""CPU-only real-provider preflight. Never print keys or HTTP request headers."""
import asyncio,json,os,sys
from app.providers import LLMRequest,OpenAICompatibleLLMProvider

async def main():
    provider=OpenAICompatibleLLMProvider(os.getenv('LLM_BASE_URL','https://api.deepseek.com'),os.environ['LLM_API_KEY'],os.getenv('LLM_MODEL','deepseek-flash'),max_tokens=256)
    try:
        text=''.join([part async for part in provider.stream(LLMRequest('请只说一句欢迎观众的话。','回答简短自然。','此问题不需要商品事实。'))])
        if not text.strip():raise ValueError('Empty spoken content')
    except Exception as exc:
        print(json.dumps({'passed':False,'errorType':type(exc).__name__,'httpStatus':getattr(getattr(exc,'response',None),'status_code',None)}));return 1
    print(json.dumps({'passed':True,'spokenCharacters':len(text),'scope':'real streaming LLM provider; CPU only'}));return 0

if __name__=='__main__':sys.exit(asyncio.run(main()))
