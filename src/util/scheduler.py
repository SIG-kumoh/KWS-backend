import schedule
import time
from datetime import datetime
from sqlalchemy.orm import Session

from database.factories import MySQLEngineFactory
from model.db_models import Server, Container
from openStack.openstack_controller import OpenStackController
from util.logger import get_logger

controller = OpenStackController()
db_connection = MySQLEngineFactory().get_instance()
backend_logger = get_logger(name='backend', log_level='INFO', save_path="./log/backend")


def delete_expired_data():
    backend_logger.info("스케줄러 실행")
    today = datetime.now().date()

    with Session(db_connection) as session, session.begin():
        expired_servers = session.query(Server).filter(Server.end_date < today).all()
        expired_containers = session.query(Container).filter(Container.end_date < today).all()

        backend_logger.info("기간 지난 서버 삭제 시작")
        for server in expired_servers:
            session.delete(server)
            controller.delete_server(server_name=server.server_name,
                                     node_name=server.node_name)

        backend_logger.info("기간 지난 컨테이너 삭제 시작")
        for container in expired_containers:
            session.delete(container)
            controller.delete_container(container_name=container.container_name,
                                        node_name=container.node_name)

        session.commit()


schedule.every().day.at("00:00").do(delete_expired_data)


def run_scheduler():
    while True:
        schedule.run_pending()
        time.sleep(1)


if __name__ == "__main__":
    run_scheduler()
