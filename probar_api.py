
import httpx
from uuid import uuid4

BASE_URL = "http://127.0.0.1:8000"


def mostrar(numero, nombre, respuesta, esperado, validar=None):
    try:
        datos = respuesta.json()
    except ValueError:
        datos = respuesta.text

    correcto = respuesta.status_code == esperado

    if correcto and validar is not None:
        correcto = validar(datos)

    print(f"\n{'[OK]' if correcto else '[FALLO]'} {numero}. {nombre}")
    print(f"Codigo HTTP: {respuesta.status_code} (esperado: {esperado})")
    print("Respuesta:", datos)

    return correcto


def probar_api():
    print("=" * 60)
    print("FASE 2 - AUDITORIA DINAMICA DE TALENTCORE API")
    print("=" * 60)

    aprobadas = 0
    total = 0
    unico = uuid4().hex[:8]

    with httpx.Client(base_url=BASE_URL, timeout=10.0) as cliente:

        def verificar(numero, nombre, respuesta, esperado, validar=None):
            nonlocal aprobadas, total
            total += 1
            correcto = mostrar(numero, nombre, respuesta, esperado, validar)
            if correcto:
                aprobadas += 1
            return correcto

        # PRUEBA 1: Verificar servidor
        respuesta = cliente.get("/health")

        verificar(
            1, "Servidor funcionando", respuesta, 200,
            lambda d: d.get("status") == "ok"
        )

        # PRUEBA 2: Comprobar ADMIN_RRHH existente
        # Valeria tiene ID 1, creada en la fase manual.
        admin_id = 1
        headers_admin = {"X-User-Id": str(admin_id)}

        respuesta = cliente.get(
            f"/api/v1/vacaciones/saldo/{admin_id}",
            headers=headers_admin
        )

        if not verificar(
            2, "Verificar administrador RRHH", respuesta, 200
        ):
            print("No se encontro al administrador con ID 1.")
            return

        # PRUEBA 3: Registrar MANAGER
        respuesta = cliente.post(
            "/api/v1/empleados",
            headers=headers_admin,
            json={
                "nombre": "Carlos Auditoria",
                "email": f"carlos_{unico}@empresa.com",
                "rol": "MANAGER",
                "anios_antiguedad": 4,
                "manager_id": None
            }
        )

        if not verificar(
            3, "Registrar MANAGER", respuesta, 201,
            lambda d: d.get("rol") == "MANAGER"
        ):
            return

        manager_id = respuesta.json()["id"]
        headers_manager = {"X-User-Id": str(manager_id)}

        # PRUEBA 4: Registrar EMPLEADO
        respuesta = cliente.post(
            "/api/v1/empleados",
            headers=headers_admin,
            json={
                "nombre": "Pedro Auditoria",
                "email": f"pedro_{unico}@empresa.com",
                "rol": "EMPLEADO",
                "anios_antiguedad": 2,
                "manager_id": manager_id
            }
        )

        if not verificar(
            4, "Registrar EMPLEADO", respuesta, 201,
            lambda d: d.get("manager_id") == manager_id
        ):
            return

        empleado_id = respuesta.json()["id"]
        headers_empleado = {"X-User-Id": str(empleado_id)}

        # PRUEBA 5: Consultar 14 dias
        respuesta = cliente.get(
            f"/api/v1/vacaciones/saldo/{empleado_id}",
            headers=headers_empleado
        )

        verificar(
            5, "Saldo inicial de 14 dias", respuesta, 200,
            lambda d: (
                d.get("dias_totales") == 14
                and d.get("saldo_disponible") == 14
            )
        )

        # PRUEBA 6: Rechazar 15 dias
        respuesta = cliente.post(
            "/api/v1/vacaciones/solicitar",
            headers=headers_empleado,
            json={
                "empleado_id": empleado_id,
                "dias_solicitados": 15,
                "motivo": "Solicitud excesiva"
            }
        )

        verificar(
            6, "Rechazar solicitud excesiva", respuesta, 400
        )

        # PRUEBA 7: Solicitar 4 dias
        respuesta = cliente.post(
            "/api/v1/vacaciones/solicitar",
            headers=headers_empleado,
            json={
                "empleado_id": empleado_id,
                "dias_solicitados": 4,
                "motivo": "Vacaciones familiares"
            }
        )

        if not verificar(
            7, "Crear solicitud pendiente", respuesta, 201,
            lambda d: d.get("estado") == "PENDING"
        ):
            return

        solicitud_id = respuesta.json()["id"]

        # PRUEBA 8: Bloquear usuario inexistente
        respuesta = cliente.post(
            f"/api/v1/vacaciones/{solicitud_id}/revisar",
            headers={"X-User-Id": "999999"},
            json={"accion": "APPROVE"}
        )

        verificar(
            8, "Bloquear usuario inexistente", respuesta, 404
        )

        # PRUEBA 9: Aprobar con jefe directo
        respuesta = cliente.post(
            f"/api/v1/vacaciones/{solicitud_id}/revisar",
            headers=headers_manager,
            json={"accion": "APPROVE"}
        )

        if not verificar(
            9, "Aprobacion del jefe directo", respuesta, 200,
            lambda d: (
                d.get("estado") == "APPROVED"
                and d.get("revisado_por_id") == manager_id
            )
        ):
            return

        # PRUEBA 10: Verificar saldo final
        respuesta = cliente.get(
            f"/api/v1/vacaciones/saldo/{empleado_id}",
            headers=headers_empleado
        )

        verificar(
            10, "Saldo final de 10 dias", respuesta, 200,
            lambda d: (
                d.get("dias_totales") == 14
                and d.get("dias_aprobados") == 4
                and d.get("saldo_disponible") == 10
            )
        )

    print("\n" + "=" * 60)
    print(f"RESULTADO FINAL: {aprobadas} DE {total} PRUEBAS APROBADAS")
    print("=" * 60)


if __name__ == "__main__":
    try:
        probar_api()
    except httpx.RequestError as error:
        print("\n[ERROR] No se pudo conectar con TalentCore.")
        print("Comprueba que Uvicorn este funcionando.")
        print(error)
