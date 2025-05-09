import asyncio
import hashlib
import os
import shutil
import sys
from pathlib import Path
import time
import platform
from dotenv import load_dotenv
from src.common.logger import get_module_logger, LogConfig, CONFIRM_STYLE_CONFIG
from src.common.crash_logger import install_crash_handler
from src.main import MainSystem
from datetime import datetime, time as dt_time

logger = get_module_logger("main_bot")
confirm_logger_config = LogConfig(
    console_format=CONFIRM_STYLE_CONFIG["console_format"],
    file_format=CONFIRM_STYLE_CONFIG["file_format"],
)
confirm_logger = get_module_logger("confirm", config=confirm_logger_config)
# 获取没有加载env时的环境变量
env_mask = {key: os.getenv(key) for key in os.environ}

uvicorn_server = None
driver = None
app = None
loop = None


def easter_egg():
    # 彩蛋
    from colorama import init, Fore

    init()
    text = "多年以后，面对AI行刑队，张三将会回想起他2023年在会议上讨论人工智能的那个下午"
    rainbow_colors = [Fore.RED, Fore.YELLOW, Fore.GREEN, Fore.CYAN, Fore.BLUE, Fore.MAGENTA]
    rainbow_text = ""
    for i, char in enumerate(text):
        rainbow_text += rainbow_colors[i % len(rainbow_colors)] + char
    print(rainbow_text)


def init_config():
    # 初次启动检测
    if not os.path.exists("config/bot_config.toml"):
        logger.warning("检测到bot_config.toml不存在，正在从模板复制")

        # 检查config目录是否存在
        if not os.path.exists("config"):
            os.makedirs("config")
            logger.info("创建config目录")

        shutil.copy("template/bot_config_template.toml", "config/bot_config.toml")
        logger.info("复制完成，请修改config/bot_config.toml和.env中的配置后重新启动")


def init_env():
    # 检测.env文件是否存在
    if not os.path.exists(".env"):
        logger.error("检测到.env文件不存在")
        shutil.copy("template/template.env", "./.env")
        logger.info("已从template/template.env复制创建.env，请修改配置后重新启动")


def load_env():
    # 直接加载生产环境变量配置
    if os.path.exists(".env"):
        load_dotenv(".env", override=True)
        logger.success("成功加载环境变量配置")
    else:
        logger.error("未找到.env文件，请确保文件存在")
        raise FileNotFoundError("未找到.env文件，请确保文件存在")


def scan_provider(env_config: dict):
    provider = {}

    # 利用未初始化 env 时获取的 env_mask 来对新的环境变量集去重
    # 避免 GPG_KEY 这样的变量干扰检查
    env_config = dict(filter(lambda item: item[0] not in env_mask, env_config.items()))

    # 遍历 env_config 的所有键
    for key in env_config:
        # 检查键是否符合 {provider}_BASE_URL 或 {provider}_KEY 的格式
        if key.endswith("_BASE_URL") or key.endswith("_KEY"):
            # 提取 provider 名称
            provider_name = key.split("_", 1)[0]  # 从左分割一次，取第一部分

            # 初始化 provider 的字典（如果尚未初始化）
            if provider_name not in provider:
                provider[provider_name] = {"url": None, "key": None}

            # 根据键的类型填充 url 或 key
            if key.endswith("_BASE_URL"):
                provider[provider_name]["url"] = env_config[key]
            elif key.endswith("_KEY"):
                provider[provider_name]["key"] = env_config[key]

    # 检查每个 provider 是否同时存在 url 和 key
    for provider_name, config in provider.items():
        if config["url"] is None or config["key"] is None:
            logger.error(f"provider 内容：{config}\nenv_config 内容：{env_config}")
            raise ValueError(f"请检查 '{provider_name}' 提供商配置是否丢失 BASE_URL 或 KEY 环境变量")


async def graceful_shutdown():
    try:
        logger.info("正在优雅关闭麦麦...")
        tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    except Exception as e:
        logger.error(f"麦麦关闭失败: {e}")


def check_eula():
    eula_confirm_file = Path("eula.confirmed")
    privacy_confirm_file = Path("privacy.confirmed")
    eula_file = Path("EULA.md")
    privacy_file = Path("PRIVACY.md")

    eula_updated = True
    eula_new_hash = None
    privacy_updated = True
    privacy_new_hash = None

    eula_confirmed = False
    privacy_confirmed = False

    # 首先计算当前EULA文件的哈希值
    if eula_file.exists():
        with open(eula_file, "r", encoding="utf-8") as f:
            eula_content = f.read()
        eula_new_hash = hashlib.md5(eula_content.encode("utf-8")).hexdigest()
    else:
        logger.error("EULA.md 文件不存在")
        raise FileNotFoundError("EULA.md 文件不存在")

    # 首先计算当前隐私条款文件的哈希值
    if privacy_file.exists():
        with open(privacy_file, "r", encoding="utf-8") as f:
            privacy_content = f.read()
        privacy_new_hash = hashlib.md5(privacy_content.encode("utf-8")).hexdigest()
    else:
        logger.error("PRIVACY.md 文件不存在")
        raise FileNotFoundError("PRIVACY.md 文件不存在")

    # 检查EULA确认文件是否存在
    if eula_confirm_file.exists():
        with open(eula_confirm_file, "r", encoding="utf-8") as f:
            confirmed_content = f.read()
        if eula_new_hash == confirmed_content:
            eula_confirmed = True
            eula_updated = False
    if eula_new_hash == os.getenv("EULA_AGREE"):
        eula_confirmed = True
        eula_updated = False

    # 检查隐私条款确认文件是否存在
    if privacy_confirm_file.exists():
        with open(privacy_confirm_file, "r", encoding="utf-8") as f:
            confirmed_content = f.read()
        if privacy_new_hash == confirmed_content:
            privacy_confirmed = True
            privacy_updated = False
    if privacy_new_hash == os.getenv("PRIVACY_AGREE"):
        privacy_confirmed = True
        privacy_updated = False

    # 如果EULA或隐私条款有更新，提示用户重新确认
    if eula_updated or privacy_updated:
        confirm_logger.critical("EULA或隐私条款内容已更新，请在阅读后重新确认，继续运行视为同意更新后的以上两款协议")
        confirm_logger.critical(
            f'输入"同意"或"confirmed"或设置环境变量"EULA_AGREE={eula_new_hash}"和"PRIVACY_AGREE={privacy_new_hash}"继续运行'
        )
        while True:
            user_input = input().strip().lower()
            if user_input in ["同意", "confirmed"]:
                # print("确认成功，继续运行")
                # print(f"确认成功，继续运行{eula_updated} {privacy_updated}")
                if eula_updated:
                    logger.info(f"更新EULA确认文件{eula_new_hash}")
                    eula_confirm_file.write_text(eula_new_hash, encoding="utf-8")
                if privacy_updated:
                    logger.info(f"更新隐私条款确认文件{privacy_new_hash}")
                    privacy_confirm_file.write_text(privacy_new_hash, encoding="utf-8")
                break
            else:
                confirm_logger.critical('请输入"同意"或"confirmed"以继续运行')
        return
    elif eula_confirmed and privacy_confirmed:
        return


def raw_main():
    # 利用 TZ 环境变量设定程序工作的时区
    if platform.system().lower() != "windows":
        time.tzset()

    # 安装崩溃日志处理器
    install_crash_handler()

    check_eula()
    print("检查EULA和隐私条款完成")
    easter_egg()
    init_config()
    init_env()
    load_env()

    env_config = {key: os.getenv(key) for key in os.environ}
    scan_provider(env_config)

    # 返回MainSystem实例
    return MainSystem()


# 修改后的 monitor_time 函数
async def monitor_time():
    await asyncio.sleep(10)
    while True:
        if not allowed_time():
            logger.info("当前时间超出允许区间，自动关闭系统。")
            break
        await asyncio.sleep(60)


# 修改后的 allowed_time 函数，支持多个时间段配置
def allowed_time():
    now = datetime.now().time()
    weekday = datetime.now().weekday()  # 周一=0, ..., 周日=6
    # 定义允许时间区间配置，支持多个时间段
    allowed_intervals = [
        ((11, 0), (13, 0)),
        ((21, 0), (23, 45))
        # ...可以继续加入更多时间段...
    ]
    # 周六和周日长一点
    if weekday in [5, 6]:
        allowed_intervals = [
            ((10, 0), (2, 0)),
            ((20, 0), (1, 30))
        # ...可以继续加入更多时间段...
        ]
    for start_tuple, end_tuple in allowed_intervals:
        start = dt_time(*start_tuple)
        end = dt_time(*end_tuple)
        if start < end:  # 不跨天
            if start <= now < end:
                return True
        else:  # 跨天处理，如 20:00 - 0:30
            if now >= start or now < end:
                return True
    return False


async def run_bot():
    while True:
        if allowed_time():
            logger.info("当前时间处于允许区间，系统上线。")
            try:
                main_system = raw_main()
                # 为每次上线创建新的事件循环环境（不用阻塞外层循环）
                await main_system.initialize()

                async def main_tasks():
                    task1 = asyncio.create_task(main_system.schedule_tasks())
                    task2 = asyncio.create_task(monitor_time())
                    done, pending = await asyncio.wait(
                        {task1, task2},
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    for task in pending:
                        task.cancel()
                    await graceful_shutdown()

                await main_tasks()

            except Exception as e:
                logger.error(f"主程序异常: {str(e)}")
        else:
            logger.info("当前时间不在允许区间，系统保持离线状态。")
        # 每60秒检查一次
        await asyncio.sleep(60)


if __name__ == "__main__":
    try:
        asyncio.run(run_bot())
    except KeyboardInterrupt:
        logger.info("检测到 Ctrl+C，程序退出。")
