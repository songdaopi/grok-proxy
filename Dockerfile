# 使用官方 Python 运行时作为基础镜像
FROM python:3.9-slim-buster

# 设置工作目录
WORKDIR /app

# 将当前目录下的所有文件复制到容器的 /app 目录下
COPY . .

# 安装所需的 Python 包
RUN pip install --no-cache-dir flask requests

# 暴露端口
EXPOSE 11451

# 定义环境变量 (可选，但推荐)
ENV GROK_API_URL=https://grok.x.com/2/grok/add_response.json
ENV FLASK_APP=openai-to-grok-proxy3.py
ENV GROK_MODEL_OPTION_ID=grok-3

# 运行应用
CMD ["flask", "run", "--port=11451"]
