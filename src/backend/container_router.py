import hashlib

from fastapi import APIRouter, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from openStack.openstack_controller import OpenStackController
from database.factories import MySQLEngineFactory
from model.api_models import ContainerCreateRequestDTO, ErrorResponse, ApiResponse, ContainerReturnRequestDTO
from model.db_models import Container, Server, Network, NodeNetwork, Node
from util.utils import create_env_dict
from util.logger import get_logger
from util.backend_utils import network_isolation, network_delete
from config.config import openstack_config, node_config


container_router = APIRouter(prefix="/container")
controller = OpenStackController()
db_connection = MySQLEngineFactory().get_instance()
backend_logger = get_logger(name='backend', log_level='INFO', save_path="./log/backend")


@container_router.post("/rental")
def rental(container_info: ContainerCreateRequestDTO):
    backend_logger.info("컨테이너 대여 요청 수신")
    with Session(db_connection) as session:
        if container_info.network_name is None:
            backend_logger.info("외부 네트워크 사용")
            container_info.network_name = openstack_config['external_network']

        backend_logger.info("컨테이너 중복 여부 검사")
        if session.scalars(select(Container).where(Container.container_name == container_info.container_name)).one_or_none() is not None:
            return ErrorResponse(status.HTTP_400_BAD_REQUEST, "컨테이너 이름 중복")

        backend_logger.info("네트워크 분리 여부 검사")
        # 해당 네트워크가 없다면
        if session.scalars(select(Network).where(Network.name == container_info.network_name)).one_or_none() is None:
            backend_logger.info("시스템에 해당 네트워크 존재하지 않음")
            backend_logger.info("데이터베이스에 네트워크 삽입")
            session.add(Network(
                name=container_info.network_name,
                cidr=container_info.subnet_cidr,
                is_default=False
            ))

        # 해당 노드의 네트워크가 없다면
        if session.scalars(select(NodeNetwork).where(NodeNetwork.network_name == container_info.network_name and
                                                     NodeNetwork.node_name == container_info.node_name)).one_or_none() is None:
            network_isolation(controller=controller,
                              node_name=container_info.node_name,
                              backend_logger=backend_logger,
                              network_name=container_info.network_name,
                              subnet_cidr=container_info.subnet_cidr)

            session.add(NodeNetwork(node_name=container_info.node_name,
                                    network_name=container_info.network_name))

        try:
            backend_logger.info("컨테이너 생성")
            container = controller.create_container(container_name=container_info.container_name,
                                                    node_name=container_info.node_name,
                                                    image_name=container_info.image_name,
                                                    network_name=container_info.network_name,
                                                    env=create_env_dict(container_info.env),
                                                    cmd=container_info.cmd)

            sha256 = hashlib.sha256()
            sha256.update(container_info.password.encode('utf-8'))
            container = Container(
                user_name=container_info.user_name,
                container_name=container_info.container_name,
                start_date=container_info.start_date,
                end_date=container_info.end_date,
                image_name=container_info.image_name,
                password=sha256.hexdigest(),
                ip=list(container.addresses.values())[0][0]['addr'],
                port=str(container.ports),
                network_name=container_info.network_name,
                node_name=container_info.node_name
            )
            backend_logger.info("데이터베이스에 인스턴스 저장")
            session.add(container)
            session.commit()
        except Exception as e:
            backend_logger.error(e)
            # 네트워크 분리 복구
            node_network = session.scalars(select(NodeNetwork).where(NodeNetwork.network_name == container_info.network_name and
                                                         NodeNetwork.node_name == container_info.node_name)).one_or_none()
            if node_network is not None and not node_network.network.is_default:
                network_delete(controller=controller,
                               node_name=container_info.node_name,
                               network_name=container_info.network_name,
                               backend_logger=backend_logger)
            session.rollback()
            controller.delete_container(container_name=container_info.container_name,
                                        node_name=container_info.node_name)
            return ErrorResponse(status.HTTP_500_INTERNAL_SERVER_ERROR, "백엔드 내부 오류")

        return ApiResponse(status.HTTP_201_CREATED, None)


@container_router.delete("/return")
def container_return(container_info: ContainerReturnRequestDTO):
    backend_logger.info("컨테이너 반환 요청 수신")
    sha256 = hashlib.sha256()
    sha256.update(container_info.password.encode('utf-8'))

    with Session(db_connection) as session:
        try:
            container = session.scalars(
                select(Container)
                .where(Container.container_name == container_info.container_name)
            ).one()

            network_name = container.network_name
            backend_logger.info("비밀번호 검사")
            if sha256.hexdigest() != container.password:
                return ErrorResponse(status.HTTP_400_BAD_REQUEST, "비밀번호가 맞지 않습니다.")

            backend_logger.info("컨테이너 삭제")
            controller.delete_container(container_name=container_info.container_name,
                                        node_name=container.node_name)
            backend_logger.info("데이터베이스에 인스턴스 삭제")
            session.delete(container)
            session.commit()

            network = session.scalars(select(Network).where(Network.name == network_name)).one()
            attached_servers_on_network = len(network.servers)
            attached_containers_on_network = len(network.containers)
            if attached_servers_on_network + attached_containers_on_network == 0 and not network.is_default:
                backend_logger.info("내부 네트워크를 사용 중인 서버/컨테이너 없음")
                backend_logger.info("내부 네트워크 삭제 시작")

                backend_logger.info("데이터베이스에 네트워크 삭제")
                target_node_networks = session.scalars(select(NodeNetwork).where(NodeNetwork.network_name == network_name)).all()
                # 외래키 제약 조건이 있으니 중간 테이블부터 삭제
                for target_node_network in target_node_networks:
                    network_delete(controller=controller,
                                   node_name=target_node_network.node_name,
                                   backend_logger=backend_logger,
                                   network_name=target_node_network.network_name)
                    session.delete(target_node_network)

                target_network = session.scalars(select(Network).where(Network.name == network_name)).one()
                session.delete(target_network)
            session.commit()
        except Exception as e:
            backend_logger.error(e)
            return ErrorResponse(status.HTTP_500_INTERNAL_SERVER_ERROR, "백엔드 내부 오류")

    return ApiResponse(status.HTTP_200_OK, None)
