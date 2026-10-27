
from fastapi import FastAPI, Depends, HTTPException, Header
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field, ConfigDict
from typing import Literal, Optional

from app.models import (
    Base, engine, get_db, Empleado, SolicitudVacaciones
)

Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="TalentCore API",
    description="Sistema de empleados y vacaciones",
    version="2.0.0"
)


# =====================================
# ESQUEMAS
# =====================================

class EmpleadoCreate(BaseModel):
    nombre: str = Field(min_length=1, max_length=100)
    email: str = Field(min_length=3, max_length=150)
    rol: Literal["ADMIN_RRHH", "MANAGER", "EMPLEADO"]
    anios_antiguedad: int = Field(ge=0)
    manager_id: Optional[int] = None


class EmpleadoResponse(EmpleadoCreate):
    id: int

    model_config = ConfigDict(from_attributes=True)


class SolicitudCreate(BaseModel):
    empleado_id: int
    dias_solicitados: int = Field(gt=0)
    motivo: str = Field(min_length=1)


class SolicitudResponse(BaseModel):
    id: int
    empleado_id: int
    dias_solicitados: int
    motivo: str
    estado: str
    revisado_por_id: Optional[int] = None

    model_config = ConfigDict(from_attributes=True)


class RevisarSolicitud(BaseModel):
    accion: Literal["APPROVE", "REJECT"]


# =====================================
# FUNCIONES AUXILIARES
# =====================================

def buscar_empleado(db: Session, empleado_id: int):
    empleado = db.get(Empleado, empleado_id)

    if empleado is None:
        raise HTTPException(
            status_code=404,
            detail="Empleado no encontrado"
        )

    return empleado


def usuario_actual(
    x_user_id: int = Header(..., alias="X-User-Id"),
    db: Session = Depends(get_db)
):
    return buscar_empleado(db, x_user_id)


def calcular_dias(anios):
    return min(12 + 2 * max(anios - 1, 0), 20)


def calcular_saldo(db, empleado):
    dias_totales = calcular_dias(empleado.anios_antiguedad)

    aprobadas = db.query(SolicitudVacaciones).filter(
        SolicitudVacaciones.empleado_id == empleado.id,
        SolicitudVacaciones.estado == "APPROVED"
    ).all()

    dias_aprobados = sum(
        solicitud.dias_solicitados for solicitud in aprobadas
    )

    return {
        "empleado_id": empleado.id,
        "dias_totales": dias_totales,
        "dias_aprobados": dias_aprobados,
        "saldo_disponible": dias_totales - dias_aprobados
    }


# =====================================
# RETO 1: HEALTH
# =====================================

@app.get("/health")
def health():
    return {"status": "ok"}


# =====================================
# RETOS 2 Y 3: REGISTRAR EMPLEADOS
# =====================================

@app.post(
    "/api/v1/empleados",
    response_model=EmpleadoResponse,
    status_code=201
)
def registrar_empleado(
    datos: EmpleadoCreate,
    db: Session = Depends(get_db),
    x_user_id: Optional[int] = Header(
        default=None,
        alias="X-User-Id"
    )
):
    total_empleados = db.query(Empleado).count()

    if total_empleados == 0:
        if datos.rol != "ADMIN_RRHH":
            raise HTTPException(
                status_code=403,
                detail="El primer usuario debe ser ADMIN_RRHH"
            )
    else:
        if x_user_id is None:
            raise HTTPException(
                status_code=403,
                detail="Se requiere X-User-Id"
            )

        usuario = buscar_empleado(db, x_user_id)

        if usuario.rol != "ADMIN_RRHH":
            raise HTTPException(
                status_code=403,
                detail="Solo ADMIN_RRHH puede registrar empleados"
            )

    existente = db.query(Empleado).filter(
        Empleado.email == datos.email
    ).first()

    if existente:
        raise HTTPException(
            status_code=400,
            detail="El correo ya esta registrado"
        )

    if datos.manager_id is not None:
        manager = buscar_empleado(db, datos.manager_id)

        if manager.rol != "MANAGER":
            raise HTTPException(
                status_code=400,
                detail="El jefe asignado debe tener rol MANAGER"
            )

    if datos.rol == "EMPLEADO" and datos.manager_id is None:
        raise HTTPException(
            status_code=400,
            detail="El empleado necesita un jefe directo"
        )

    empleado = Empleado(**datos.model_dump())

    db.add(empleado)
    db.commit()
    db.refresh(empleado)

    return empleado


# =====================================
# RETO 4: CONSULTAR SALDO
# =====================================

@app.get("/api/v1/vacaciones/saldo/{empleado_id}")
def consultar_saldo(
    empleado_id: int,
    db: Session = Depends(get_db),
    usuario: Empleado = Depends(usuario_actual)
):
    empleado = buscar_empleado(db, empleado_id)

    autorizado = (
        usuario.rol == "ADMIN_RRHH"
        or usuario.id == empleado.id
        or (
            usuario.rol == "MANAGER"
            and empleado.manager_id == usuario.id
        )
    )

    if not autorizado:
        raise HTTPException(
            status_code=403,
            detail="No tienes permiso para consultar este saldo"
        )

    return calcular_saldo(db, empleado)


# =====================================
# RETOS 5 Y 6: SOLICITAR VACACIONES
# =====================================

@app.post(
    "/api/v1/vacaciones/solicitar",
    response_model=SolicitudResponse,
    status_code=201
)
def solicitar_vacaciones(
    datos: SolicitudCreate,
    db: Session = Depends(get_db),
    usuario: Empleado = Depends(usuario_actual)
):
    if usuario.rol != "EMPLEADO":
        raise HTTPException(
            status_code=403,
            detail="Solo EMPLEADO puede solicitar vacaciones"
        )

    if datos.empleado_id != usuario.id:
        raise HTTPException(
            status_code=403,
            detail="No puedes solicitar vacaciones para otro empleado"
        )

    saldo = calcular_saldo(db, usuario)

    pendientes = db.query(SolicitudVacaciones).filter(
        SolicitudVacaciones.empleado_id == usuario.id,
        SolicitudVacaciones.estado == "PENDING"
    ).all()

    dias_pendientes = sum(
        solicitud.dias_solicitados for solicitud in pendientes
    )

    disponibles = saldo["saldo_disponible"] - dias_pendientes

    if datos.dias_solicitados > disponibles:
        raise HTTPException(
            status_code=400,
            detail="Insufficient vacation balance"
        )

    solicitud = SolicitudVacaciones(
        empleado_id=datos.empleado_id,
        dias_solicitados=datos.dias_solicitados,
        motivo=datos.motivo,
        estado="PENDING"
    )

    db.add(solicitud)
    db.commit()
    db.refresh(solicitud)

    return solicitud


# =====================================
# RETO 7: REVISAR SOLICITUD
# =====================================

@app.post(
    "/api/v1/vacaciones/{solicitud_id}/revisar",
    response_model=SolicitudResponse
)
def revisar_solicitud(
    solicitud_id: int,
    datos: RevisarSolicitud,
    db: Session = Depends(get_db),
    usuario: Empleado = Depends(usuario_actual)
):
    solicitud = db.get(SolicitudVacaciones, solicitud_id)

    if solicitud is None:
        raise HTTPException(
            status_code=404,
            detail="Solicitud no encontrada"
        )

    empleado = buscar_empleado(db, solicitud.empleado_id)

    # AC-03: Solo el jefe directo puede revisar.
    if (
        usuario.rol != "MANAGER"
        or empleado.manager_id != usuario.id
    ):
        raise HTTPException(
            status_code=403,
            detail="Solo el jefe directo puede revisar esta solicitud"
        )

    if solicitud.estado != "PENDING":
        raise HTTPException(
            status_code=400,
            detail="La solicitud ya fue revisada"
        )

    if datos.accion == "APPROVE":
        saldo = calcular_saldo(db, empleado)

        if solicitud.dias_solicitados > saldo["saldo_disponible"]:
            raise HTTPException(
                status_code=400,
                detail="Insufficient vacation balance"
            )

        solicitud.estado = "APPROVED"
    else:
        solicitud.estado = "REJECTED"

    solicitud.revisado_por_id = usuario.id

    db.commit()
    db.refresh(solicitud)

    return solicitud
