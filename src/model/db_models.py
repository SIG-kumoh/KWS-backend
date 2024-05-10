import datetime
from sqlalchemy import Integer, String, Date
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Server(Base):
    __tablename__ = "server"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_name: Mapped[str] = mapped_column(String(45))
    server_name: Mapped[str] = mapped_column(String(45), unique=True)
    start_date: Mapped[datetime] = mapped_column(Date)
    end_date: Mapped[datetime] = mapped_column(Date)
    floating_ip: Mapped[str] = mapped_column(String(45))
    network_name: Mapped[str] = mapped_column(String(45))
    node_name: Mapped[str] = mapped_column(String(45))
    flavor_name: Mapped[str] = mapped_column(String(45))
    image_name: Mapped[str] = mapped_column(String(45))
