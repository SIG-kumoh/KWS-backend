import io
from datetime import date
from fastapi import APIRouter, Form, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from database.factories import MySQLEngineFactory
from model.db_models import Server
from model.api_models import ApiResponse, ServersResponseDTO
from util.utils import validate_ssh_key


db_router = APIRouter(prefix="/db")
db_connection = MySQLEngineFactory().get_instance()


@db_router.get("/servers")
def server_show():
    with Session(db_connection) as session, session.begin():
        servers = session.scalars(select(Server)).all()
        server_list = []
        for server in servers:
            server_dict = server.__dict__
            del server_dict['id']
            del server_dict['_sa_instance_state']
            server_list.append(ServersResponseDTO(**server_dict))
        return ApiResponse(status.HTTP_200_OK, server_list)


@db_router.put("/extension")
def server_renew(server_name: str = Form(...),
                 host_ip: str = Form(...),
                 end_date: str = Form(...),
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
                split_date = end_date.split(sep='-')
                server.end_date = date(int(split_date[0]), int(split_date[1]), int(split_date[2]))
                session.add(server)
                session.commit()
            except:
                session.rollback()
                return ApiResponse(status.HTTP_500_INTERNAL_SERVER_ERROR, "예외 상황 발생")
        return ApiResponse(status.HTTP_200_OK, "대여 기간 연장 완료")
    else:
        return ApiResponse(status.HTTP_400_BAD_REQUEST, "입력한 정보가 잘못됨")