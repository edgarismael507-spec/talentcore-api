import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app, Base
from app.models import get_db, Empleado, SolicitudVacaciones

# Configuración de la base de datos de prueba en memoria
SQLALCHEMY_DATABASE_URL = "sqlite://"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)

TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def override_get_db():
    try:
        db = TestingSessionLocal()
        yield db
    finally:
        db.close()

app.dependency_overrides[get_db] = override_get_db

@pytest.fixture(autouse=True)
def setup_database():
    """
    Crea las tablas antes de cada prueba y las elimina después.
    Garantiza aislamiento entre pruebas.
    """
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)

@pytest.fixture
def client():
    return TestClient(app)

@pytest.fixture
def admin_user(client):
    """Crea un usuario ADMIN y devuelve su ID."""
    response = client.post(
        "/api/v1/empleados",
        json={
            "nombre": "Admin Test",
            "rol": "ADMIN",
            "saldo_vacaciones": 10
        }
    )
    assert response.status_code == 201
    return response.json()["id"]

@pytest.fixture
def regular_user(client):
    """Crea un usuario EMPLEADO y devuelve su ID."""
    response = client.post(
        "/api/v1/empleados",
        json={
            "nombre": "Empleado Test",
            "rol": "EMPLEADO",
            "saldo_vacaciones": 5
        }
    )
    assert response.status_code == 201
    return response.json()["id"]

class TestHealthEndpoint:
    def test_health_check(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

class TestEmpleadoRegistration:
    def test_register_employee_success(self, client):
        response = client.post(
            "/api/v1/empleados",
            json={
                "nombre": "Juan Perez",
                "rol": "EMPLEADO",
                "saldo_vacaciones": 15
            }
        )
        assert response.status_code == 201
        data = response.json()
        assert data["nombre"] == "Juan Perez"
        assert data["rol"] == "EMPLEADO"
        assert data["saldo_vacaciones"] == 15
        assert "id" in data

    def test_register_admin_success(self, client):
        response = client.post(
            "/api/v1/empleados",
            json={
                "nombre": "Maria Lopez",
                "rol": "ADMIN",
                "saldo_vacaciones": 0
            }
        )
        assert response.status_code == 201
        data = response.json()
        assert data["rol"] == "ADMIN"

    def test_register_employee_invalid_rol(self, client):
        response = client.post(
            "/api/v1/empleados",
            json={
                "nombre": "Invalid Rol",
                "rol": "SUPERVISOR",
                "saldo_vacaciones": 10
            }
        )
        assert response.status_code == 422

    def test_register_employee_empty_name(self, client):
        response = client.post(
            "/api/v1/empleados",
            json={
                "nombre": "",
                "rol": "EMPLEADO",
                "saldo_vacaciones": 10
            }
        )
        assert response.status_code == 422

    def test_register_employee_negative_balance(self, client):
        response = client.post(
            "/api/v1/empleados",
            json={
                "nombre": "Negative Balance",
                "rol": "EMPLEADO",
                "saldo_vacaciones": -5
            }
        )
        assert response.status_code == 422

class TestConsultarSaldo:
    def test_admin_can_check_any_balance(self, client, admin_user, regular_user):
        response = client.get(
            f"/api/v1/vacaciones/saldo/{regular_user}",
            headers={"X-User-Id": str(admin_user)}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["empleado_id"] == regular_user
        assert data["saldo_vacaciones"] == 5

    def test_employee_can_check_own_balance(self, client, regular_user):
        response = client.get(
            f"/api/v1/vacaciones/saldo/{regular_user}",
            headers={"X-User-Id": str(regular_user)}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["empleado_id"] == regular_user
        assert data["saldo_vacaciones"] == 5

    def test_employee_cannot_check_other_balance(self, client, regular_user, admin_user):
        # Intenta un empleado regular consultar el saldo de otro (aunque sea admin, la lógica es rol != ADMIN y id != empleado_id)
        # En este caso, regular_user intenta consultar a admin_user
        response = client.get(
            f"/api/v1/vacaciones/saldo/{admin_user}",
            headers={"X-User-Id": str(regular_user)}
        )
        assert response.status_code == 403
        assert response.json()["detail"] == "No puedes consultar el saldo de otro empleado"

    def test_nonexistent_employee_balance(self, client, admin_user):
        response = client.get(
            "/api/v1/vacaciones/saldo/99999",
            headers={"X-User-Id": str(admin_user)}
        )
        assert response.status_code == 404
        assert response.json()["detail"] == "Empleado no encontrado"

    def test_missing_header(self, client, regular_user):
        response = client.get(f"/api/v1/vacaciones/saldo/{regular_user}")
        assert response.status_code == 422

class TestSolicitarVacaciones:
    def test_employee_can_request_vacations(self, client, regular_user):
        response = client.post(
            "/api/v1/vacaciones/solicitar",
            json={"dias_solicitados": 3},
            headers={"X-User-Id": str(regular_user)}
        )
        assert response.status_code == 201
        data = response.json()
        assert data["empleado_id"] == regular_user
        assert data["dias_solicitados"] == 3
        assert data["estado"] == "PENDIENTE"

    def test_admin_cannot_request_vacations(self, client, admin_user):
        response = client.post(
            "/api/v1/vacaciones/solicitar",
            json={"dias_solicitados": 3},
            headers={"X-User-Id": str(admin_user)}
        )
        assert response.status_code == 403
        assert response.json()["detail"] == "Solo los empleados pueden solicitar vacaciones"

    def test_request_exceeds_balance(self, client, regular_user):
        # Saldo es 5, solicita 6
        response = client.post(
            "/api/v1/vacaciones/solicitar",
            json={"dias_solicitados": 6},
            headers={"X-User-Id": str(regular_user)}
        )
        assert response.status_code == 400
        assert response.json()["detail"] == "Saldo de vacaciones insuficiente"

    def test_request_exceeds_balance_with_pending(self, client, regular_user):
        # Saldo es 5.
        # Solicita 3 (PENDIENTE). Disponible: 5 - 3 = 2.
        client.post(
            "/api/v1/vacaciones/solicitar",
            json={"dias_solicitados": 3},
            headers={"X-User-Id": str(regular_user)}
        )
        # Intenta solicitar 3 más. Disponible: 2. 3 > 2 -> Error
        response = client.post(
            "/api/v1/vacaciones/solicitar",
            json={"dias_solicitados": 3},
            headers={"X-User-Id": str(regular_user)}
        )
        assert response.status_code == 400
        assert response.json()["detail"] == "Saldo de vacaciones insuficiente"

    def test_request_zero_days(self, client, regular_user):
        response = client.post(
            "/api/v1/vacaciones/solicitar",
            json={"dias_solicitados": 0},
            headers={"X-User-Id": str(regular_user)}
        )
        assert response.status_code == 422

class TestRevisarSolicitud:
    def test_admin_can_approve_request(self, client, admin_user, regular_user):
        # Crear solicitud
        req_response = client.post(
            "/api/v1/vacaciones/solicitar",
            json={"dias_solicitados": 2},
            headers={"X-User-Id": str(regular_user)}
        )
        solicitud_id = req_response.json()["id"]

        # Aprobar
        response = client.post(
            f"/api/v1/vacaciones/{solicitud_id}/revisar",
            json={"estado": "APROBADA"},
           
            headers={"X-User-Id": str(admin_user)}
        )

        assert response.status_code == 200
        assert response.json()["estado"] == "APROBADA"

        # Comprobar que se descontaron los dias
        saldo = client.get(
            f"/api/v1/vacaciones/saldo/{regular_user}",
            headers={"X-User-Id": str(regular_user)}
        )

        assert saldo.status_code == 200
        assert saldo.json()["saldo_vacaciones"] == 3

    def test_admin_can_reject_request(
        self, client, admin_user, regular_user
    ):
        solicitud = client.post(
            "/api/v1/vacaciones/solicitar",
            json={"dias_solicitados": 2},
            headers={"X-User-Id": str(regular_user)}
        )

        solicitud_id = solicitud.json()["id"]

        response = client.post(
            f"/api/v1/vacaciones/{solicitud_id}/revisar",
            json={"estado": "RECHAZADA"},
            headers={"X-User-Id": str(admin_user)}
        )

        assert response.status_code == 200
        assert response.json()["estado"] == "RECHAZADA"

        # Rechazar no debe descontar dias
        saldo = client.get(
            f"/api/v1/vacaciones/saldo/{regular_user}",
            headers={"X-User-Id": str(regular_user)}
        )

        assert saldo.json()["saldo_vacaciones"] == 5

    def test_employee_cannot_approve(
        self, client, regular_user
    ):
        solicitud = client.post(
            "/api/v1/vacaciones/solicitar",
            json={"dias_solicitados": 2},
            headers={"X-User-Id": str(regular_user)}
        )

        solicitud_id = solicitud.json()["id"]

        response = client.post(
            f"/api/v1/vacaciones/{solicitud_id}/revisar",
            json={"estado": "APROBADA"},
            headers={"X-User-Id": str(regular_user)}
        )

        assert response.status_code == 403

    def test_cannot_review_twice(
        self, client, admin_user, regular_user
    ):
        solicitud = client.post(
            "/api/v1/vacaciones/solicitar",
            json={"dias_solicitados": 2},
            headers={"X-User-Id": str(regular_user)}
        )

        solicitud_id = solicitud.json()["id"]

        url = f"/api/v1/vacaciones/{solicitud_id}/revisar"
        headers = {"X-User-Id": str(admin_user)}

        primera = client.post(
            url,
            json={"estado": "APROBADA"},
            headers=headers
        )

        assert primera.status_code == 200

        segunda = client.post(
            url,
            json={"estado": "RECHAZADA"},
            headers=headers
        )

        assert segunda.status_code == 400
