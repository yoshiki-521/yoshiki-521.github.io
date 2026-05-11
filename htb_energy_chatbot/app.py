from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import httpx 
import os 
import certifi 
from dotenv import load_dotenv 
from fastapi.middleware.cors import CORSMiddleware 
import traceback 
from datetime import datetime


load_dotenv()

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True, 
    allow_methods=["*"], 
    allow_headers=["*"],
)

DIFY_API_URL = "https://api.dify.ai/v1/chat-messages"
DIFY_API_KEY = os.getenv("DIFY_API_KEY")
KINTONE_DOMAIN = os.getenv("KINTONE_DOMAIN")
KINTONE_APP_ID = os.getenv("KINTONE_APP_ID")
KINTONE_API_TOKEN = os.getenv("KINTONE_API_TOKEN")

class ChatInput(BaseModel):
    question: str
    user_id: str = "web-user"

class FeedbackPayload(BaseModel):
    message_id: str
    conversation_id: str
    query: str
    answer: str
    rating: str

@app.post("/api/chat")
async def chat(input: ChatInput):
    headers = {
        "Authorization": f"Bearer {DIFY_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "query": input.question,
        "response_mode": "blocking",
        "user": input.user_id,
        "inputs": {}
    }

    try:
        async with httpx.AsyncClient(
        verify=certifi.where(),
        timeout=httpx.Timeout(30.0)
    ) as client:
            response = await client.post(DIFY_API_URL, headers=headers, json=payload)
            response.raise_for_status()
            chat_json = response.json()

        message_id = chat_json.get("id")
        conversation_id = chat_json.get("conversation_id")
         
        headers = {
            "X-Cybozu-API-Token": KINTONE_API_TOKEN,
            "Content-Type": "application/json"
        }
        
        body = {
            "app": KINTONE_APP_ID,
            "record": {
                "日時": { "value": datetime.now().isoformat() },
                "message_id": { "value": message_id },
                "conversation_id": { "value": conversation_id },
                "query": { "value": input.question },
                "answer": { "value": chat_json.get("answer", "") }
            }
        }
        
        async with httpx.AsyncClient() as client:
            await client.post(f"{KINTONE_DOMAIN}/k/v1/record.json", headers=headers, json=body)
        
        return {
            "answer": chat_json.get("answer", ""),
            "message_id": message_id,
            "conversation_id": conversation_id  
        }
    
    except Exception as e:
        print(" Dify API通信失敗:", str(e))
        traceback.print_exc()
        return {"error": "Dify API接続に失敗しました", "details": str(e)}

@app.post("/api/feedback")
async def update_feedback(payload: FeedbackPayload):
    kintone_headers = {
        "X-Cybozu-API-Token": KINTONE_API_TOKEN
    }

    message_id_str = str(payload.message_id).strip()
    query_string = f'message_id = "{message_id_str}"'

    try:
        async with httpx.AsyncClient() as client:
            search_res = await client.get(
                f"{KINTONE_DOMAIN}/k/v1/records.json",
                headers=kintone_headers,
                params={
                    "app": KINTONE_APP_ID,
                    "query": query_string
                }
            )

            search_res.raise_for_status()
            record_json = search_res.json()

            if "records" not in record_json or not record_json["records"]:
                raise HTTPException(status_code=404, detail="対象のレコードが存在しません")

            record_id = record_json["records"][0]["$id"]["value"]

            update_body = {
                "app": KINTONE_APP_ID,
                "id": record_id,
                "record": {
                    "rating": {"value": payload.rating}
                }
            }

            update_res = await client.put(
                f"{KINTONE_DOMAIN}/k/v1/record.json",
                headers=kintone_headers,
                json=update_body
            )
            update_res.raise_for_status()

            return {"status": "updated"}

    except Exception as e:
        print(" kintone評価更新失敗:", e)
        raise HTTPException(status_code=500, detail="Kintoneへの評価更新に失敗しました")