from dynaconf import Dynaconf
import logging
import colorlog

settings = Dynaconf(
    envvar_prefix="DYNACONF",
    settings_files=["settings.toml", ".secrets.toml"],
)

log_handler = colorlog.StreamHandler()
log_handler.setFormatter(
    colorlog.ColoredFormatter(
        "%(log_color)s%(asctime)s %(name)s[%(funcName)s] - %(levelname)s: %(message)s"
    )
)

log = colorlog.getLogger("WiseBot")
log.addHandler(log_handler)
log.setLevel(settings.log.level)
colorlog.getLogger().setLevel(logging.DEBUG)
colorlog.getLogger("discord").addHandler(log_handler)
colorlog.getLogger("discord").setLevel(logging.INFO)
