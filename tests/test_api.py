
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app, Base
from app.models import get_db


# Base de datos temporal para las pruebas.
# No modifica talentcore.db.
engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool
)

TestingSessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)


@pytest.fixture
def client():
    Base.metadata.create_all(bind=engine)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)


def crear_admin(client):
    respuesta = client.post(
        "/api/v1/empleados",
        json={
            "nombre": "Administrador",
            "email": "admin@talentcore.test",
            "rol": "ADMIN_RRHH",
            "anios_antiguedad": 1,
            "manager_id": None
        }
    )
    assert respuesta.status_code == 201, respuesta.text
    return respuesta.json()["id"]


def crear_manager(client, admin_id):
    respuesta = client.post(
        "/api/v1/empleados",
        headers={"X-User-Id": str(admin_id)},
        json={
            "nombre": "Carlos Manager",
            "email": "manager@talentcore.test",
            "rol": "MANAGER",
            "anios_antiguedad": 2,
            "manager_id": None
        }
    )
    assert respuesta.status_code == 201, respuesta.text
    return respuesta.json()["id"]


def crear_empleado(client, admin_id, manager_id):
    respuesta = client.post(
        "/api/v1/empleados",
        headers={"X-User-Id": str(admin_id)},
        json={
            "nombre": "Pedro Empleado",
            "email": "empleado@talentcore.test",
            "rol": "EMPLEADO",
            "anios_antiguedad": 3,
            "manager_id": manager_id
        }
    )
    assert respuesta.status_code == 201, respuesta.text
    return respuesta.json()["id"]


def crear_equipo(client):
    admin_id = crear_admin(client)
    manager_id = crear_manager(client, admin_id)
    empleado_id = crear_empleado(client, admin_id, manager_id)
    return admin_id, manager_id, empleado_id


def solicitar(client, empleado_id, dias=5):
    return client.post(
        "/api/v1/vacaciones/solicitar",
        headers={"X-User-Id": str(empleado_id)},
        json={
            "empleado_id": empleado_id,
            "dias_solicitados": dias,
            "motivo": "Vacaciones familiares"
        }
    )


def revisar(client, manager_id, solicitud_id, accion):
    return client.post(
        f"/api/v1/vacaciones/{solicitud_id}/revisar",
        headers={"X-User-Id": str(manager_id)},
        json={"accion": accion}
    )


# =====================================
# PRUEBAS DE SALUD
# =====================================

def test_health(client):
    respuesta = client.get("/health")
    assert respuesta.status_code == 200
    assert respuesta.json() == {"status": "ok"}


# =====================================
# PRUEBAS DE EMPLEADOS
# =====================================

def test_crear_primer_administrador(client):
    admin_id = crear_admin(client)
    assert admin_id > 0


def test_primer_usuario_debe_ser_admin(client):
    respuesta = client.post(
        "/api/v1/empleados",
        json={
            "nombre": "Usuario",
            "email": "usuario@talentcore.test",
            "rol": "EMPLEADO",
            "anios_antiguedad": 1,
            "manager_id": None
        }
    )
    assert respuesta.status_code == 403


def test_crear_manager(client):
    admin_id = crear_admin(client)
    manager_id = crear_manager(client, admin_id)
    assert manager_id > 0


def test_crear_empleado_con_jefe(client):
    _, _, empleado_id = crear_equipo(client)
    assert empleado_id > 0


def test_empleado_sin_jefe(client):
    admin_id = crear_admin(client)

    respuesta = client.post(
        "/api/v1/empleados",
        headers={"X-User-Id": str(admin_id)},
        json={
            "nombre": "Sin Jefe",
            "email": "sinjefe@talentcore.test",
            "rol": "EMPLEADO",
            "anios_antiguedad": 1,
            "manager_id": None
        }
    )
    assert respuesta.status_code == 400


def test_correo_duplicado(client):
    admin_id = crear_admin(client)

    respuesta = client.post(
        "/api/v1/empleados",
        headers={"X-User-Id": str(admin_id)},
        json={
            "nombre": "Otro Administrador",
            "email": "admin@talentcore.test",
            "rol": "ADMIN_RRHH",
            "anios_antiguedad": 1,
            "manager_id": None
        }
    )
    assert respuesta.status_code == 400


def test_rol_invalido(client):
    respuesta = client.post(
        "/api/v1/empleados",
        json={
            "nombre": "Usuario",
            "email": "invalido@talentcore.test",
            "rol": "SUPERVISOR",
            "anios_antiguedad": 1,
            "manager_id": None
        }
    )
    assert respuesta.status_code == 422


# =====================================
# PRUEBAS DE SALDO
# =====================================

def test_saldo_inicial(client):
    _, _, empleado_id = crear_equipo(client)

    respuesta = client.get(
        f"/api/v1/vacaciones/saldo/{empleado_id}",
        headers={"X-User-Id": str(empleado_id)}
    )

    assert respuesta.status_code == 200
    assert respuesta.json()["dias_totales"] == 16
    assert respuesta.json()["saldo_disponible"] == 16


def test_admin_consulta_saldo(client):
    admin_id, _, empleado_id = crear_equipo(client)

    respuesta = client.get(
        f"/api/v1/vacaciones/saldo/{empleado_id}",
        headers={"X-User-Id": str(admin_id)}
    )
    assert respuesta.status_code == 200


def test_manager_consulta_saldo(client):
    _, manager_id, empleado_id = crear_equipo(client)

    respuesta = client.get(
        f"/api/v1/vacaciones/saldo/{empleado_id}",
        headers={"X-User-Id": str(manager_id)}
    )
    assert respuesta.status_code == 200


def test_saldo_sin_header(client):
    _, _, empleado_id = crear_equipo(client)

    respuesta = client.get(
        f"/api/v1/vacaciones/saldo/{empleado_id}"
    )
    assert respuesta.status_code == 422


def test_saldo_empleado_inexistente(client):
    admin_id = crear_admin(client)

    respuesta = client.get(
        "/api/v1/vacaciones/saldo/99999",
        headers={"X-User-Id": str(admin_id)}
    )
    assert respuesta.status_code == 404


# =====================================
# PRUEBAS DE SOLICITUDES
# =====================================

def test_solicitar_vacaciones(client):
    _, _, empleado_id = crear_equipo(client)

    respuesta = solicitar(client, empleado_id, 5)

    assert respuesta.status_code == 201
    assert respuesta.json()["estado"] == "PENDING"
    assert respuesta.json()["dias_solicitados"] == 5


def test_solicitud_excesiva(client):
    _, _, empleado_id = crear_equipo(client)

    respuesta = solicitar(client, empleado_id, 20)
    assert respuesta.status_code == 400


def test_solicitud_dias_cero(client):
    _, _, empleado_id = crear_equipo(client)

    respuesta = solicitar(client, empleado_id, 0)
    assert respuesta.status_code == 422


def test_solicitud_para_otro_empleado(client):
    admin_id, _, empleado_id = crear_equipo(client)

    respuesta = client.post(
        "/api/v1/vacaciones/solicitar",
        headers={"X-User-Id": str(empleado_id)},
        json={
            "empleado_id": admin_id,
            "dias_solicitados": 2,
            "motivo": "Vacaciones"
        }
    )
    assert respuesta.status_code == 403


def test_solicitudes_pendientes_restan_disponibilidad(client):
    _, _, empleado_id = crear_equipo(client)

    primera = solicitar(client, empleado_id, 10)
    segunda = solicitar(client, empleado_id, 7)

    assert primera.status_code == 201
    assert segunda.status_code == 400


# =====================================
# PRUEBAS DE APROBACION
# =====================================

def test_manager_aprueba(client):
    _, manager_id, empleado_id = crear_equipo(client)

    solicitud = solicitar(client, empleado_id, 5)
    assert solicitud.status_code == 201

    respuesta = revisar(
        client, manager_id, solicitud.json()["id"], "APPROVE"
    )

    assert respuesta.status_code == 200
    assert respuesta.json()["estado"] == "APPROVED"

    saldo = client.get(
        f"/api/v1/vacaciones/saldo/{empleado_id}",
        headers={"X-User-Id": str(empleado_id)}
    )
    assert saldo.json()["saldo_disponible"] == 11


def test_manager_rechaza(client):
    _, manager_id, empleado_id = crear_equipo(client)

    solicitud = solicitar(client, empleado_id, 5)

    respuesta = revisar(
        client, manager_id, solicitud.json()["id"], "REJECT"
    )

    assert respuesta.status_code == 200
    assert respuesta.json()["estado"] == "REJECTED"

    saldo = client.get(
        f"/api/v1/vacaciones/saldo/{empleado_id}",
        headers={"X-User-Id": str(empleado_id)}
    )
    assert saldo.json()["saldo_disponible"] == 16


def test_empleado_no_puede_aprobar(client):
    _, _, empleado_id = crear_equipo(client)

    solicitud = solicitar(client, empleado_id, 2)

    respuesta = revisar(
        client, empleado_id, solicitud.json()["id"], "APPROVE"
    )
    assert respuesta.status_code == 403


def test_admin_no_es_jefe_directo(client):
    admin_id, _, empleado_id = crear_equipo(client)

    solicitud = solicitar(client, empleado_id, 2)

    respuesta = revisar(
        client, admin_id, solicitud.json()["id"], "APPROVE"
    )
    assert respuesta.status_code == 403


def test_no_revisar_dos_veces(client):
    _, manager_id, empleado_id = crear_equipo(client)

    solicitud = solicitar(client, empleado_id, 2)
    solicitud_id = solicitud.json()["id"]

    primera = revisar(client, manager_id, solicitud_id, "APPROVE")
    segunda = revisar(client, manager_id, solicitud_id, "REJECT")

    assert primera.status_code == 200
    assert segunda.status_code == 400


def test_solicitud_inexistente(client):
    _, manager_id, _ = crear_equipo(client)

    respuesta = revisar(client, manager_id, 99999, "APPROVE")
    assert respuesta.status_code == 404
