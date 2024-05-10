import io
from fastapi import APIRouter, Form, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from database.factories import MySQLEngineFactory
from model.db_models import Server
from model.api_models import (ApiResponse, ServerCreateRequestDTO, ServerRentalResponseDTO, ImageListResponseDTO,
                              FlavorListResponseDTO, ResourcesResponseDTO)
from openStack.openstack_controller import OpenStackController
from util.utils import validate_ssh_key

openstack_router = APIRouter(prefix="/openstack")
controller = OpenStackController()
db_connection = MySQLEngineFactory().get_instance()


@openstack_router.post("/rental")
def server_rent(server_info: ServerCreateRequestDTO):
    if controller.find_server(server_info.server_name) is not None:
        return ApiResponse(status.HTTP_400_BAD_REQUEST, "서버 이름 중복")

    with Session(db_connection) as session:
        session.begin()
        try:
            server, private_key = controller.create_server(server_info)
            floating_ip = controller.allocate_floating_ip(server)

            server = Server(
                user_name=server_info.user_name,
                server_name=server_info.server_name,
                start_date=server_info.start_date,
                end_date=server_info.end_date,
                floating_ip=floating_ip,
                network_name=server_info.network_name,
                node_name=server_info.node_name,
                flavor_name=server_info.flavor_name,
                image_name=server_info.image_name
            )
            session.add(server)
            session.commit()
        except:
            session.rollback()
            controller.delete_server(server_info.server_name, floating_ip)
            return ApiResponse(status.HTTP_500_INTERNAL_SERVER_ERROR, "예외 상황 발생")
        
    name = f'{server_info.server_name}_keypair.pem' if private_key != "" else ""
    return ApiResponse(status.HTTP_201_CREATED, ServerRentalResponseDTO(name, private_key))


@openstack_router.get("/image_list")
def image_list_show():
    try:
        images = controller.find_images()
    except:
        return ApiResponse(status.HTTP_500_INTERNAL_SERVER_ERROR, "예외 상황 발생")

    image_list = [ImageListResponseDTO(image.name) for image in images]
    return ApiResponse(status.HTTP_200_OK, image_list)


@openstack_router.get("/flavor_list")
def flavor_list_show():
    try:
        flavors = controller.find_flavors()
    except:
        return status.HTTP_500_INTERNAL_SERVER_ERROR

    flavor_list = [FlavorListResponseDTO(flavor.name, flavor.vcpus, flavor.ram, flavor.disk) for flavor in flavors]
    flavor_list = sorted(flavor_list, key=lambda f: (f.cpu, f.ram, f.disk))
    return ApiResponse(status.HTTP_200_OK, flavor_list)


@openstack_router.delete("/return")
async def server_return(server_name: str = Form(...),
                        host_ip: str = Form(...),
                        password: str = Form(""),
                        key_file: UploadFile = Form("")):
    key_file = io.StringIO(key_file.file.read().decode('utf-8')) \
        if key_file != "" else key_file

    if validate_ssh_key(host_name=host_ip,
                        user_name=server_name,
                        private_key=key_file,
                        password=password):
        with Session(db_connection) as session:
            session.begin()

            try:
                server = session.scalars(
                    select(Server)
                    .where(Server.server_name == server_name)
                ).one()
                session.delete(server)
                controller.delete_server(server_name, host_ip)
                session.commit()
            except:
                session.rollback()
                return ApiResponse(status.HTTP_500_INTERNAL_SERVER_ERROR, "예외 상황 발생")

        return ApiResponse(status.HTTP_200_OK, "서버 삭제 완료")
    else:
        return ApiResponse(status.HTTP_400_BAD_REQUEST, "입력한 정보가 잘못됨")


@openstack_router.get("/resources")
def get_resources():
    return ApiResponse(status.HTTP_200_OK, ResourcesResponseDTO(**controller.monitoring_resources()))


@openstack_router.get("/resources/{node_name}")
def get_resource(node_name):
    with Session(db_connection) as session, session.begin():
        servers = session.scalars(select(Server).where(Server.node_name == node_name))
        count = 0
        vcpus = 0
        ram = 0
        disk = 0

        for server in servers:
            count += 1
            flavor = controller.find_flavor(flavor_name=server.flavor_name)
            vcpus += flavor.vcpus
            ram += flavor.ram
            disk += flavor.disk

    resource_dict = {
        "count": count,
        "vcpus": vcpus,
        "ram": float(ram / 1024),
        "disk": disk
    }

    return ApiResponse(status.HTTP_200_OK, ResourcesResponseDTO(**resource_dict))
