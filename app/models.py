
from sqlalchemy import create_engine, Column, Integer, String, ForeignKey
from sqlalchemy.orm import declarative_base, sessionmaker, relationship

SQLALCHEMY_DATABASE_URL = "sqlite:///./talentcore.db"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False}
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)

Base = declarative_base()


class Empleado(Base):
    __tablename__ = "empleados"

    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String(100), nullable=False)
    email = Column(String(150), unique=True, nullable=False)
    rol = Column(String(20), nullable=False)
    anios_antiguedad = Column(Integer, nullable=False, default=0)

    # Un administrador puede existir sin jefe directo.
    manager_id = Column(
        Integer,
        ForeignKey("empleados.id"),
        nullable=True
    )

    manager = relationship(
        "Empleado",
        remote_side=[id],
        back_populates="subordinados"
    )

    subordinados = relationship(
        "Empleado",
        back_populates="manager"
    )

    solicitudes = relationship(
        "SolicitudVacaciones",
        back_populates="empleado",
        foreign_keys="SolicitudVacaciones.empleado_id"
    )


class SolicitudVacaciones(Base):
    __tablename__ = "solicitudes_vacaciones"

    id = Column(Integer, primary_key=True, index=True)

    empleado_id = Column(
        Integer,
        ForeignKey("empleados.id"),
        nullable=False
    )

    dias_solicitados = Column(Integer, nullable=False)
    motivo = Column(String(255), nullable=False)
    estado = Column(String(20), nullable=False, default="PENDING")

    revisado_por_id = Column(
        Integer,
        ForeignKey("empleados.id"),
        nullable=True
    )

    empleado = relationship(
        "Empleado",
        back_populates="solicitudes",
        foreign_keys=[empleado_id]
    )

    revisado_por = relationship(
        "Empleado",
        foreign_keys=[revisado_por_id]
    )


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
