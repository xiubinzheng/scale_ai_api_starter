from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()


class EchoRequest(BaseModel):
    text: str


@app.get('/hello_world')
def hello_world():
    return {'hello': 'world'}


@app.post('/echo')
def echo(payload: EchoRequest):
    return {'text': payload.text}
