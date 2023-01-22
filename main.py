import asyncio
import logging

from pydantic import BaseSettings, AmqpDsn, IPvAnyAddress

from src.service import Gateway

logging.basicConfig(level=logging.INFO)


class Config(BaseSettings):
    MQTT_BROKER: AmqpDsn
    HOST_IP: IPvAnyAddress = '127.0.0.1'
    HOST_PORT: int = 2065
    AUV_TOPIK: str = 'auv'

    class Config:
        case_sensitive = True


async def main():
    config = Config()
    gateway = Gateway(config.MQTT_BROKER.host, config.HOST_IP,
        config.MQTT_BROKER.port, config.HOST_PORT, config.AUV_TOPIK)
    try:
        await gateway.run()
    except Exception as e:
        gateway.close()
        raise e
    finally:
        gateway.close()


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info('Выход')
