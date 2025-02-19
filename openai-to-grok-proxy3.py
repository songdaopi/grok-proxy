import flask
import requests
import json
import time
import uuid

app = flask.Flask(__name__)

# Grok 后端回复接口 URL，请确认该 URL 是否正确
GROK_API_URL = "https://grok.x.com/2/grok/add_response.json"

# CreateGrokConversation 接口的 URL（请替换为你自己的地址）
CREATE_CONVERSATION_URL = "https://x.com/i/api/graphql/.../CreateGrokConversation"

# 以下认证参数请替换为你自己的值,QUERY_ID即https://x.com/i/api/graphql/"..."/CreateGrokConversation中...的值
CT0 = "..."
CSRF_TOKEN = "..."
QUERY_ID = "..."

def create_grok_conversation(auth_bearer, auth_token):
    """
    调用 CreateGrokConversation 接口生成新的 conversationId
    返回的 JSON 示例：
      {
          "data": {
              "create_grok_conversation": {
                  "conversation_id": "1892158011344617851"
              }
          }
      }
    """
    headers = {
        'authorization': f'Bearer {auth_bearer}',
        # Cookie 中同时包含 ct0 与 auth_token
        'Cookie': f'ct0={CT0}; auth_token={auth_token}',
        'Content-Type': 'application/json',
        'x-csrf-token': CSRF_TOKEN
    }
    data = {"variables": {}, "queryId": QUERY_ID}
    try:
        response = requests.post(CREATE_CONVERSATION_URL, headers=headers, json=data, timeout=10)
        response.raise_for_status()
        resp_json = response.json()
        print("CreateGrokConversation 返回的 JSON：", resp_json)
        
        # 尝试按驼峰格式获取，若没有则尝试下划线格式
        if "data" in resp_json and isinstance(resp_json["data"], dict):
            conv_data = resp_json["data"].get("createGrokConversation")
            if conv_data and isinstance(conv_data, dict) and "conversationId" in conv_data:
                return conv_data["conversationId"]
            conv_data = resp_json["data"].get("create_grok_conversation")
            if conv_data and isinstance(conv_data, dict) and "conversation_id" in conv_data:
                return conv_data["conversation_id"]
        
        print("返回的 JSON 结构与预期不符，无法找到 conversationId:", resp_json)
        return None
    except Exception as e:
        print("创建 Grok 会话失败:", e)
        return None

@app.route('/v1/chat/completions', methods=['POST'])
def openai_to_grok_proxy():
    # 解析 Authorization 头部（格式：Bearer $AUTH_BEARER,$AUTH_TOKEN）
    auth_header = flask.request.headers.get('authorization')
    if not auth_header:
        return "Authorization 头部缺失", 401
    try:
        auth_bearer, auth_token = auth_header.split("Bearer ")[1].split(",")
    except Exception:
        return "Authorization 头部格式错误，应为 'Bearer $AUTH_BEARER,$AUTH_TOKEN'", 400

    # 获取请求体，要求为 JSON 格式且包含 'messages' 字段
    openai_request_data = flask.request.get_json()
    if not openai_request_data or 'messages' not in openai_request_data:
        return "请求体无效，必须包含 'messages' 字段", 400

    messages = openai_request_data['messages']
    if not messages:
        return "'messages' 不能为空", 400

    # 找到最后一条用户消息
    last_user_message = None
    for message in reversed(messages):
        if message.get('role') == 'user':
            last_user_message = message.get('content')
            break
    if not last_user_message:
        return "消息列表中未找到 'user' 角色的消息", 400

    # 如无 conversationId，则调用 CreateGrokConversation 接口生成新的 conversationId
    conversation_id = openai_request_data.get('conversationId')
    if not conversation_id:
        conversation_id = create_grok_conversation(auth_bearer, auth_token)
        if not conversation_id:
            return "创建 Grok 会话失败", 500

    # 如果存在 system 消息，则合并这些提示并追加 "INPUT:" 后再加上用户消息
    system_messages = [msg.get("content", "") for msg in messages if msg.get("role") == "system"]
    if system_messages:
        combined_message = "\n".join(system_messages).strip() + "\n\nINPUT: " + last_user_message
    else:
        combined_message = last_user_message

    # 获取可选的 promptSource 与 action 参数（默认为 "NATURAL" 和 "EDIT"）
    prompt_source = openai_request_data.get("promptSource", "NATURAL")
    action_param = openai_request_data.get("action", "EDIT")

    # 构建发送给 Grok API 的请求头
    grok_request_headers = {
        'authorization': f'Bearer {auth_bearer}',
        'content-type': 'application/json; charset=UTF-8',
        'accept-encoding': 'gzip, deflate, br, zstd',
        'cookie': f'auth_token={auth_token}'
    }

    # 构造发送给 Grok API 的请求体
    grok_request_body = {
        "responses": [
            {
                "message": combined_message,
                "sender": 1,  # 此处约定 1 表示用户
                "fileAttachments": []
            }
        ],
        "grokModelOptionId": os.environ.get("GROK_MODEL_OPTION_ID", "grok-2"),
        "conversationId": conversation_id,
        "promptSource": prompt_source,
        "action": action_param
    }
    # 如果请求中包含 resampleResponseId，则传递该参数
    if "resampleResponseId" in openai_request_data:
        grok_request_body["resampleResponseId"] = openai_request_data["resampleResponseId"]

    def generate():
        try:
            with requests.post(GROK_API_URL, headers=grok_request_headers, json=grok_request_body, stream=True) as grok_response:
                grok_response.raise_for_status()
                openai_chunk_id = "chatcmpl-" + uuid.uuid4().hex
                openai_created_time = int(time.time())
                openai_model = openai_request_data.get("model", "grok-1")
                for line in grok_response.iter_lines():
                    if line:
                        try:
                            grok_data = json.loads(line.decode("utf-8"))
                            extra_fields = {}
                            if "resampleResponseId" in grok_data.get("result", {}):
                                extra_fields["resampleResponseId"] = grok_data["result"]["resampleResponseId"]
                            if ('result' in grok_data and 
                                grok_data['result'].get("sender") == "ASSISTANT"):
                                message_content = grok_data['result'].get("message", "")
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
                                openai_chunk.update(extra_fields)
                                yield f"data: {json.dumps(openai_chunk)}\n\n"
                            elif ('result' in grok_data and 
                                  grok_data['result'].get("isSoftStop") is True):
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
                                openai_chunk_stop.update(extra_fields)
                                yield f"data: {json.dumps(openai_chunk_stop)}\n\n"
                        except json.JSONDecodeError:
                            print("警告：无法解码 JSON：", line.decode("utf-8"))
                        except Exception as e:
                            print("处理 Grok 响应 chunk 时出错：", e)
                yield "data: [DONE]\n\n"
        except requests.exceptions.RequestException as e:
            error_message = f"Grok API 请求失败: {e}"
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
            
    return flask.Response(flask.stream_with_context(generate()), mimetype="text/event-stream")

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