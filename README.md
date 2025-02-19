# 使用教程 (2版):
原作者（类脑dc）：[aexk233.](https://discord.com/channels/1134557553011998840/1341413677504663643)
原作的原作：[grok](https://github.com/omgpizzatnt/grok-web-api)
## 1. 获取 Grok 的 auth_bearer 和 auth_token:

同一开始写的，不变

## 2. 获取 Grok 的 conversationId:

仍然在 Grok 网页版 (https://grok.x.com/) 上。

创建一个新的聊天 (或者打开一个你想要继续上下文的现有聊天)。

重要步骤: 为了获取 conversationId，最简单的方法是在新创建的空白聊天中先发送一条消息 (例如，随便输入一个句号 ".")，或者打开一个已有的聊天。

再次打开浏览器的开发者工具 (F12)，切换到 “网络 (Network)” 选项卡。

在网络请求列表中，找到你刚刚发送消息时发出的请求，点进client_event.json，找到referer: https://x.com/i/grok?focus=1&conversation=xxxxx
其中，xxxxx就是这个对话的id，它的值就是你当前聊天的 conversationId。复制这个值。

注意: 每个新的聊天会话都有不同的 conversationId。如果你想在 SillyTavern 中维持上下文，你需要使用同一个 conversationId。

## 3. 部署和运行 openai-to-grok-proxy2.py:

### 附：使用docker部署
使用 Docker 运行 openai-to-grok-proxy2 简易教程

**1. 拉取镜像：**

```bash
docker pull ghcr.io/songdaopi/grok-proxy:main
```

**2. 运行容器：**

```bash
docker run -d -p 11451:11451 --name openai-grok-proxy ghcr.io/songdaopi/grok-proxy:main
```

*   `-d`: 后台运行。
*   `-p 11451:11451`: 端口映射，将宿主机的 11451 端口映射到容器的 11451 端口。
*   `--name openai-grok-proxy`: 容器命名。

**3. 测试：**

现在，你可以通过访问 `http://<your_host_ip>:11451/v1/chat/completions` 来使用代理服务了。将 `<your_host_ip>` 替换为你的服务器 IP 地址或 `localhost`（如果你在本地运行）。

**可选：** 使用 `docker logs -f openai-grok-proxy` 实时查看容器日志。


确保你已经安装了 Python 和 Flask, requests 库。 如果没有安装，请使用 pip 安装。

右键点击我给的.py，使用python启动

服务器默认会在 http://192.168.31.122:11451 启动。请注意， 192.168.31.122 是代码中默认监听的 IP 地址，你需要根据你的实际网络环境和需求修改代码中的 host 参数。 如果你想在本地所有 IP 地址上监听，可以将 host 设置为 '0.0.0.0'。

4. 配置 SillyTavern 连接到代理:

打开 SillyTavern，进入插头设置。

填写URL为http://192.168.31.122:11451/v1（如果改过服务器IP和端口，则按照你自己改的来）

API 密钥 (API Key): 输入你的 auth_bearer 和 auth_token，用逗号 , 分隔，格式为： $AUTH_BEARER,$AUTH_TOKEN (例如： abcdefg12345,hijklmn67890)。 

重要步骤 - 添加 conversationId 到请求体:

在 SillyTavern 的插头设置中，打开“附加参数”，在“包括主体参数”栏目内填入你刚刚获取的conversationId
```
{
    "conversationId": "xxxxx"
}
```
保存附加参数。

5. 开始对话:

在 SillyTavern 中选择你配置的 OpenAI (Grok 代理) 连接。

开始与你的角色对话。 现在，你的对话应该能够保持上下文了，因为代理会将 conversationId 传递给 Grok API。
