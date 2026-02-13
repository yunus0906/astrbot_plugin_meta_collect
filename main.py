import aiohttp
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api.message_components import Image, Plain, Video
from astrbot.api import logger

# 文件类型对应的 Emoji 映射
EMOJI_MAP = {
    "IMAGE": "🖼️",
    "VIDEO": "📹",
    "PDF": "📄",
    "ZIP": "📦",
    "BOOK": "📚",
    "TEXT": "📝",
    "DEFAULT": "📁"
}

@register("astrbot_plugin_meta_collect", "yunus", "元采集平台搜索插件", "1.0.0")
class MelonSearchPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        # 基础接口地址
        self.base_url = "http://localhost:8080"

    # ==========================================================
    # 指令：/搜瓜 [关键词]
    # ==========================================================
    @filter.command("搜瓜")
    async def search_melon(self, event: AstrMessageEvent):
        """搜瓜 <关键词>"""
        # 1. 获取关键词
        parts = event.message_str.split(maxsplit=1)
        keyword = parts[1].strip() if len(parts) > 1 else ""

        if not keyword:
            yield event.plain_result("请输入搜索关键词，例如：/搜瓜 demo")
            return

        # 2. 准备接口请求
        url = f"{self.base_url}/media/mediaData/web/list"
        params = {
            "contentText": keyword,
            "status": "enable"
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params) as resp:
                    if resp.status != 200:
                        yield event.plain_result(f"搜索接口请求失败，状态码: {resp.status}")
                        return
                    data = await resp.json()
        except Exception as e:
            logger.error(f"搜瓜接口异常: {e}")
            yield event.plain_result(f"连接接口时发生错误: {e}")
            return

        # 3. 处理返回数据
        if not data:
            yield event.plain_result(f"搜索【{keyword}】，未查到相关信息。")
            return

        # 获取结果数量
        count = len(data)

        # 4. 构建返回文本
        msg_lines = [
            f" 搜索【{keyword}】，共查到 {count} 条信息："
        ]

        for item in data:
            # ID 获取逻辑
            cid = item.get("code")
            if not cid:
                cid = item.get("id")

            title = item.get("title", "无标题")

            # 类型与Emoji处理
            file_type = item.get("fileType", "DEFAULT")
            emoji = EMOJI_MAP.get(file_type, EMOJI_MAP["DEFAULT"])

            # 格式：【ID】【Emoji 类型】【标题】
            msg_lines.append(f" {emoji}【{cid}】{title}")

        msg_lines.append("\n输入 /cid [CODE] 获取详情")
        msg_lines.append("如需解压密码请查看公告")

        # 发送文本结果
        yield event.plain_result("\n".join(msg_lines))
    # ==========================================================
    # 指令：/cid [CODE]
    # ==========================================================
    @filter.command("cid")
    async def query_detail(self, event: AstrMessageEvent):
        """cid <CODE> 获取详情"""
        # 1. 获取 ID 参数
        parts = event.message_str.split(maxsplit=1)
        cid_arg = parts[1].strip() if len(parts) > 1 else ""

        if not cid_arg:
            yield event.plain_result("请输入Code，例如：/cid 2001")
            return

        # 2. 准备接口请求
        url = f"{self.base_url}/media/mediaData/web/query"
        params = {
            "code": cid_arg
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params) as resp:
                    if resp.status != 200:
                        yield event.plain_result(f"详情接口请求失败，状态码: {resp.status}")
                        return
                    raw_data = await resp.json()
        except Exception as e:
            logger.error(f"搜瓜详情接口异常: {e}")
            yield event.plain_result(f"获取详情失败: {e}")
            return

        # 数据解析兼容 (List 或 Dict)
        data = None
        if isinstance(raw_data, list) and len(raw_data) > 0:
            data = raw_data[0]
        elif isinstance(raw_data, dict):
            data = raw_data

        if not data:
            yield event.plain_result("未找到对应的详情内容。")
            return

        # 3. 提取基础字段
        title = data.get("title", "")
        cover_url = data.get("coverUrl", "")
        file_type = data.get("fileType", "DEFAULT")
        netdisk_type = data.get("netdiskType", "未知网盘")
        netdisk_url = data.get("netdiskUrl", "无链接")

        # 4. 构建图文消息链
        chain = []

        # --- 标题 ---
        chain.append(Plain(f"{title}\n"))

        # --- 封面主图 ---
        if cover_url:
            chain.append(Image.fromURL(cover_url))

        # --- 根据类型展示额外媒体 ---

        # 处理 IMAGE 类型：展示多图
        if file_type == "IMAGE":
            images_str = data.get("imagesUrl", "")
            if images_str:
                # 逗号分割，去除空白项
                img_urls = [url.strip() for url in images_str.split(",") if url.strip()]
                for url in img_urls:
                    chain.append(Image.fromURL(url))

        # 处理 VIDEO 类型：展示视频
        elif file_type == "VIDEO":
            # 优先尝试从 fileUrls (假设这里存的是直链) 或 extJson 中获取
            # 如果没有直链，AstrBot无法直接发送视频，只能发链接
            video_url = data.get("fileUrls")
            # 注意：如果 videoUrls 是 ID，通常无法直接下载，这里假设 fileUrls 存有可访问链接

            if video_url:
                # 如果是多个视频链接，取第一个
                v_url = video_url.split(",")[0].strip()
                if v_url:
                    chain.append(Video.fromURL(v_url))
            else:
                # 如果没有直链，提示用户查看下方的网盘链接
                chain.append(Plain("\n(视频请通过下方网盘链接观看)"))

        # 处理 PDF 类型：展示预览图或提示
        elif file_type == "PDF":
            pdf_preview_str = data.get("fileUrls", "")
            if pdf_preview_str:
                # 逗号分割，去除空白项
                pdf_urls = [url.strip() for url in pdf_preview_str.split(",") if url.strip()]
                for url in pdf_urls:
                    chain.append(Image.fromURL(url))
            else:
                chain.append(Plain("\n(PDF 文件请通过下方网盘链接下载查看)"))

        # --- 网盘详情 ---
        if netdisk_url:
            chain.append(Plain(f"\n详情：【{netdisk_type}】【{netdisk_url}】"))

        yield event.chain_result(chain)

    async def initialize(self):
        pass

    async def terminate(self):
        pass