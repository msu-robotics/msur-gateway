from src.service import Gateway
from pydantic import BaseSettings, AmqpDsn, IPvAnyAddress
import asyncio
import logging
logging.basicConfig(level=logging.INFO)


class Config(BaseSettings):
    MQTT_BROKER: AmqpDsn
    HOST_IP: IPvAnyAddress = '127.0.0.1'
    HOST_PORT: int = 9000
    TELEMETRY_TOPIK: str = 'auv/telemetry'
    CONTROL_TOPIK: str = 'auv/control'

    class Config:
        case_sensitive = True


async def main():
    config = Config()
    gateway = Gateway(config.MQTT_BROKER.host, config.HOST_IP,
        config.MQTT_BROKER.port, config.HOST_PORT, config.TELEMETRY_TOPIK,
        config.CONTROL_TOPIK)
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
