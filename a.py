import flask
import requests
import json
import time  # 导入 time 模块

app = flask.Flask(__name__)

GROK_API_URL = "https://grok.x.com/2/grok/add_response.json"

# 处理 OpenAI 聊天补全请求的路由
@app.route('/v1/chat/completions', methods=['POST'])
def openai_to_grok_proxy():
    # 获取 Authorization 头部
    auth_header = flask.request.headers.get('authorization')
    if not auth_header:
        return "Authorization 头部缺失", 401

    try:
        # 从 Authorization 头部解析 auth_bearer 和 auth_token
        auth_bearer, auth_token = auth_header.split("Bearer ")[1].split(",")
    except ValueError:
        return "Authorization 头部格式错误。应为 'Bearer $AUTH_BEARER,$AUTH_TOKEN'", 400

    # 获取请求体 (JSON 格式)
    openai_request_data = flask.request.get_json()
    if not openai_request_data or 'messages' not in openai_request_data:
        return "请求体无效。请求体中应包含 'messages'", 400

    # 获取消息列表
    messages = openai_request_data['messages']
    if not messages:
        return "'messages' 不能为空", 400

    # 找到最后一条用户消息
    last_user_message = None
    for message in reversed(messages):
        if message['role'] == 'user':
            last_user_message = message['content']
            break

    if not last_user_message:
        return "消息列表中未找到 'user' 角色的消息", 400

    # 获取 conversationId，如果请求中包含
    conversation_id = openai_request_data.get('conversationId')
    if not conversation_id:
        return "请求体中应包含 'conversationId' 以支持上下文对话", 400  # 强制要求 conversationId

    # 构建 Grok API 请求头部
    grok_request_headers = {
        'authorization': f'Bearer {auth_bearer}',
        'content-type': 'application/json; charset=UTF-8',  # 重要：设置为 application/json
        'accept-encoding': 'gzip, deflate, br, zstd',
        'cookie': f'auth_token={auth_token}'
    }

    # 构建 Grok API 请求体
    grok_request_body = {
        "responses": [
            {
                "message": last_user_message,
                "sender": 1,  # 假设 Grok API 中 sender 为 1 表示用户
                "fileAttachments": []
            }
        ],
        "grokModelOptionId": "grok-3",
        "conversationId": conversation_id  # 添加 conversationId
    }

    # 定义生成器函数，用于流式传输响应
    def generate():
        try:
            # 向 Grok API 发送 POST 请求，并启用流式传输
            with requests.post(GROK_API_URL, headers=grok_request_headers, json=grok_request_body, stream=True) as grok_response:
                grok_response.raise_for_status()  # 如果响应状态码不是 2xx，抛出异常

                openai_chunk_id = "chatcmpl-xxxxxxxxxxxxxxxxxxxxxxxx"  # 生成唯一的 ID（如果需要）
                openai_created_time = int(time.time())  # 使用当前时间戳
                openai_model = "grok-1"  # 或从 openai_request_data.get('model') 获取模型名称（如果需要）

                # 逐行迭代 Grok API 的响应
                for line in grok_response.iter_lines():
                    if line:  # 过滤掉 keep-alive 新行
                        try:
                            # 将字节解码为字符串，然后解析 JSON
                            grok_data = json.loads(line.decode('utf-8'))
                            # 检查响应中是否包含 'result'、'sender' 以及 'sender' 是否为 'ASSISTANT'
                            if 'result' in grok_data and 'sender' in grok_data['result'] and grok_data['result']['sender'] == 'ASSISTANT':
                                # 获取消息内容
                                message_content = grok_data['result'].get('message', '')
                                # 构建 OpenAI 格式的 chunk
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
                                # 通过 yield 返回 chunk
                                yield f"data: {json.dumps(openai_chunk)}\n\n"
                            # 检查响应中是否包含 'result'、'isSoftStop' 以及 'isSoftStop' 是否为 True
                            elif 'result' in grok_data and 'isSoftStop' in grok_data['result'] and grok_data['result']['isSoftStop'] is True:
                                # 构建 OpenAI 格式的停止 chunk
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
                                # 通过 yield 返回停止 chunk
                                yield f"data: {json.dumps(openai_chunk_stop)}\n\n"

                        except json.JSONDecodeError:
                            print(f"警告：无法解码 JSON：{line.decode('utf-8')}")  # 记录无效的 JSON 行
                        except Exception as e:
                            print(f"处理 Grok 响应 chunk 时出错：{e}")  # 记录处理过程中的其他异常

                # 发送表示流结束的信号
                yield "data: [DONE]\n\n"

        except requests.exceptions.RequestException as e:
            error_message = f"Grok API 请求失败：{e}"
            print(error_message)
            # 构建 OpenAI 格式的错误 chunk
            openai_error_chunk = {
                "error": {
                    "message": error_message,
                    "type": "api_error",  # 或其他适当的错误类型
                    "param": None,
                    "code": None  # 或具体的错误代码（如果可用）
                }
            }
            # 通过 yield 返回错误 chunk
            yield f"data: {json.dumps(openai_error_chunk)}\n\n"
            yield "data: [DONE]\n\n"  # 即使发生错误，也发送 DONE 来关闭流

    # 返回 Flask Response 对象，使用流式传输
    return flask.Response(flask.stream_with_context(generate()), mimetype='text/event-stream')

# 处理 /models 请求的路由，模拟 OpenAI API 的模型列表
@app.route('/models', methods=['GET'])
def list_models():
    models_data = {
        "data": [
            {
                "id": "grok-1",  # 使用与 /v1/chat/completions 中相同的模型名称
                "object": "model",
                "created": 1678882457,  # 一个有效的时间戳 (可以使用固定值)
                "owned_by": "grok", # or "openai",  "organization-owner"
                "permission": [{"id":"modelperm-u0nCNBkqoe", "object":"model_permission", "created":1704157713,"allow_create_engine":False,"allow_sampling":True,"allow_logprobs":True,"allow_search_indices":False,"allow_view":True,"allow_fine_tuning":False,"organization":"*","group":None,"is_blocking":False}]

            }
        ],
        "object": "list"
    }
    return flask.jsonify(models_data)  # 将字典转换为 JSON 响应

if __name__ == '__main__':
    app.run(host='192.168.31.122', port=11451) # 监听的ip和端口