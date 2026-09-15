from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from app.agent import run_browser_task


app = FastAPI(
	title='Browser Research Agent API',
	description='API for executing browser research tasks using Browser Use.',
	version='1.0.0',
)


app.add_middleware(
	CORSMiddleware,
	allow_origins=[
		'http://localhost:3000',
		'http://127.0.0.1:3000',
	],
	allow_credentials=True,
	allow_methods=['*'],
	allow_headers=['*'],
)


class ResearchRequest(BaseModel):
	task: str = Field(
		...,
		min_length=3,
		max_length=2000,
		description='The browser research task to execute.',
	)


@app.get('/')
def root():
	return {'message': 'Browser Research Agent API is running'}


@app.get('/health')
def health():
	return {'status': 'healthy'}


@app.post('/research')
def research(request: ResearchRequest):
	try:
		result = run_browser_task(request.task)

		if not result.get('success'):
			raise HTTPException(
				status_code=502,
				detail=result.get('error', 'Browser research failed.'),
			)

		return result

	except HTTPException:
		raise

	except Exception as e:
		raise HTTPException(
			status_code=500,
			detail=str(e),
		)
