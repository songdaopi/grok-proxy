import flask
import requests
import json
import time
import uuid

app = flask.Flask(__name__)

# Grok 后端回复接口 URL（请根据实际情况确认该 URL 是否正确）
GROK_API_URL = "https://grok.x.com/2/grok/add_response.json"

@app.route('/v1/chat/completions', methods=['POST'])
def openai_to_grok_proxy():
    # 解析 Authorization 头部（格式应为：Bearer $AUTH_BEARER,$AUTH_TOKEN）
    auth_header = flask.request.headers.get('authorization')
    if not auth_header:
        return "Authorization header missing", 401
    try:
        auth_bearer, auth_token = auth_header.split("Bearer ")[1].split(",")
    except ValueError:
        return "Authorization header format error. Should be 'Bearer $AUTH_BEARER,$AUTH_TOKEN'", 400

    # 获取请求体，需要是 JSON 格式且包含 'messages' 字段
    openai_request_data = flask.request.get_json()
    if not openai_request_data or 'messages' not in openai_request_data:
        return "Invalid request body; must include 'messages'", 400

    messages = openai_request_data['messages']
    if not messages:
        return "'messages' cannot be empty", 400

    # 从消息列表中找到最后一条用户消息
    last_user_message = None
    for message in reversed(messages):
        if message.get('role') == 'user':
            last_user_message = message.get('content')
            break
    if not last_user_message:
        return "No 'user' message found in messages", 400

    # 如果存在系统提示（role 为 system）的消息，则将所有的系统提示合并后，在前面加入提示词，再加上用户消息
    role_cards = [msg.get('content', '') for msg in messages if msg.get('role') == 'system']
    if role_cards:
        combined_message = "\n".join(role_cards).strip() + "\n\nINPUT: " + last_user_message
    else:
        combined_message = last_user_message

    # 获取 conversationId，如果请求中没有则返回错误（如有需要可在此处生成或默认一个 ID）
    conversation_id = openai_request_data.get('conversationId')
    if not conversation_id:
        return "Request body must include 'conversationId'", 400

    # 构建调用 Grok API 的请求头
    grok_request_headers = {
        'authorization': f'Bearer {auth_bearer}',
        'content-type': 'application/json; charset=UTF-8',
        'accept-encoding': 'gzip, deflate, br, zstd',
        'cookie': f'auth_token={auth_token}'
    }

    # 构造发送给 Grok 后端的请求体，message 字段使用上面合并后的消息
    grok_request_body = {
        "responses": [
            {
                "message": combined_message,
                "sender": 1,  # 假设 1 表示用户
                "fileAttachments": []
            }
        ],
        "grokModelOptionId": os.environ.get("GROK_MODEL_OPTION_ID", "grok-2"),
        "conversationId": conversation_id
    }

    # 定义生成器函数，通过流式转发 Grok API 的响应
    def generate():
        try:
            with requests.post(GROK_API_URL,
                               headers=grok_request_headers,
                               json=grok_request_body,
                               stream=True) as grok_response:
                grok_response.raise_for_status()

                # 生成一个唯一的 chunk ID
                openai_chunk_id = "chatcmpl-" + uuid.uuid4().hex
                openai_created_time = int(time.time())
                # 这里固定使用模型名称，也可以从请求中获取 openai_request_data.get('model')
                openai_model = "grok-1"

                # 逐行遍历 Grok 后端返回的流式响应
                for line in grok_response.iter_lines():
                    if line:  # 跳过空行
                        try:
                            grok_data = json.loads(line.decode('utf-8'))
                            # 如果接收到的消息中 sender 为 ASSISTANT，则构造一个 OpenAI 格式的响应块
                            if ('result' in grok_data and 
                                grok_data['result'].get('sender') == 'ASSISTANT'):
                                message_content = grok_data['result'].get('message', '')
                                openai_chunk = {
                                    "id": openai_chunk_id,
                                    "choices": [{
                                        "index": 0,
                                        "delta": {"role": "assistant", "content": message_content},
                                        "logprobs": None,
                                        "finish_reason": None
                                    }],
                                    "created": openai_created_time,
                                    "model": openai_model,
                                    "object": "chat.completion.chunk"
                                }
                                yield f"data: {json.dumps(openai_chunk)}\n\n"
                            # 如果标记了 isSoftStop，则发送结束信号
                            elif ('result' in grok_data and 
                                  grok_data['result'].get('isSoftStop') is True):
                                openai_chunk_stop = {
                                    "id": openai_chunk_id,
                                    "choices": [{
                                        "index": 0,
                                        "delta": {},
                                        "logprobs": None,
                                        "finish_reason": "stop"
                                    }],
                                    "created": openai_created_time,
                                    "model": openai_model,
                                    "object": "chat.completion.chunk"
                                }
                                yield f"data: {json.dumps(openai_chunk_stop)}\n\n"

                        except json.JSONDecodeError:
                            print("Warning: unable to decode JSON:", line.decode('utf-8'))
                        except Exception as e:
                            print("Error processing chunk:", e)
                yield "data: [DONE]\n\n"

        except requests.exceptions.RequestException as e:
            error_message = f"Grok API request failed: {e}"
            print(error_message)
            openai_error_chunk = {
                "error": {
                    "message": error_message,
                    "type": "api_error",
                    "param": None,
                    "code": None
                }
            }
            yield f"data: {json.dumps(openai_error_chunk)}\n\n"
            yield "data: [DONE]\n\n"

    return flask.Response(flask.stream_with_context(generate()), mimetype='text/event-stream')

# 模拟 OpenAI 的 /models 接口，返回模型列表
@app.route('/models', methods=['GET'])
def list_models():
    models_data = {
        "data": [
            {
                "id": "grok-1",
                "object": "model",
                "created": 1678882457,
                "owned_by": "grok",
                "permission": [{
                    "id": "modelperm-u0nCNBkqoe",
                    "object": "model_permission",
                    "created": 1704157713,
                    "allow_create_engine": False,
                    "allow_sampling": True,
                    "allow_logprobs": True,
                    "allow_search_indices": False,
                    "allow_view": True,
                    "allow_fine_tuning": False,
                    "organization": "*",
                    "group": None,
                    "is_blocking": False
                }]
            }
        ],
        "object": "list"
    }
    return flask.jsonify(models_data)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=11451)