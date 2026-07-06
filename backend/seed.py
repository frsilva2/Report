"""Popula dados de exemplo para testar o PoC.

    python seed.py

Cria:
  - 1 operador (central):   operador@wfm.local / senha123
  - 1 funcionário de campo: guarda@wfm.local   / senha123  (com embedding facial fake)
  - 1 posto (geofence) na Av. Paulista, raio 150 m
"""
from app.db.session import Base, SessionLocal, engine
from app.core.security import hash_password
from app.models.models import Role, Site, User
from app.models.models import utcnow


def run() -> None:
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        if db.query(User).count() > 0:
            print("Já existem dados — pulando seed.")
            return

        op = User(name="Central Operador", email="operador@wfm.local",
                  hashed_password=hash_password("senha123"), role=Role.operator)
        guard = User(name="João da Silva", email="guarda@wfm.local",
                     cpf="25774435016",  # placeholder; Datavalid valida contra a base por CPF
                     hashed_password=hash_password("senha123"), role=Role.employee,
                     face_embedding="[0.11,0.22,0.33]",  # placeholder do vetor base
                     consent_version="v1", consent_granted_at=utcnow())
        site = Site(name="Posto Av. Paulista", latitude=-23.561414, longitude=-46.655881, radius_m=150.0)

        db.add_all([op, guard, site])
        db.commit()
        print("Seed OK.")
        print("  Operador : operador@wfm.local / senha123")
        print("  Guarda   : guarda@wfm.local   / senha123")
        print(f"  Posto #{site.id}: {site.name} (raio {site.radius_m:.0f} m)")
    finally:
        db.close()


if __name__ == "__main__":
    run()
