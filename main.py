import aiohttp
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api.message_components import Image, Plain
from astrbot.api import logger


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
        keyword = event.message_str.split(maxsplit=1)
        keyword = keyword[1].strip() if len(keyword) > 1 else ""

        if not keyword:
            yield event.plain_result("请输入搜索关键词，例如：/搜瓜 demo")
            return

        # 2. 准备接口请求
        url = f"{self.base_url}/media/mediaData/web/list"
        # 假设接口接受 GET 请求参数，如果是 POST JSON，请修改 verify=False 等配置
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

        # 4. 构建返回文本
        # 格式：
        # ---
        # 搜索【关键词】，共查到以下信息：
        # 【categoryId】【title】
        # ...
        # ---
        msg_lines = [
            f" 搜索【{keyword}】，共查到以下信息："
        ]

        for item in data:
            # 如果 code 为空，这里默认使用 id 字段作为展示和后续查询的ID
            # 逻辑：优先显示 code，如果没有则显示 id
            cid = item.get("code")
            if not cid:
                cid = item.get("id")

            title = item.get("title", "无标题")
            type = item.get("fileType", "空类型")
            msg_lines.append(f" 【{cid}】【{type}】【{title}】\n")

        msg_lines.append("输入/cid+前面的数字，获取详情")
        msg_lines.append("如需解压密码请查看公告")

        # 发送文本结果
        yield event.plain_result("\n".join(msg_lines))

    # ==========================================================
    # 指令：/cid [ID]
    # ==========================================================
    @filter.command("cid")
    async def query_detail(self, event: AstrMessageEvent):
        """cid <ID> 获取详情"""
        # 1. 获取 ID 参数
        # cid_arg = event.message_str.replace("/cid", "").strip()
        cid_arg = event.message_str.split(maxsplit=1)
        cid_arg = cid_arg[1].strip() if len(cid_arg) > 1 else ""
        if not cid_arg:
            yield event.plain_result("请输入ID，例如：/cid 2001")
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
                    # 注意：通常查询详情返回的是单个对象，但也可能是列表包含一个对象
                    # 这里做兼容处理
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

        # 3. 提取字段
        title = data.get("title", "")
        cover_url = data.get("coverUrl", "")
        netdisk_type = data.get("netdiskType", "未知网盘")
        netdisk_url = data.get("netdiskUrl", "无链接")

        # 4. 构建图文消息链
        # 格式：
        # ---
        # 内容1【图片】
        # 内容2【网盘类型】【网盘链接】
        # ---
        chain = []

        chain.append(Plain(f"{title}"))  # 内容1

        # 如果有图片链接，插入图片组件
        if cover_url:
            chain.append(Image.fromURL(cover_url))

        chain.append(Plain(f"\n详情：【{netdisk_type}】【{netdisk_url}】\n"))  # 内容2

        yield event.chain_result(chain)

    async def initialize(self):
        pass

    async def terminate(self):
        pass