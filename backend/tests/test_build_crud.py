"""Test: Build CRUD operations — save, retrieve, update."""

import os
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base, get_db
from app.models.build import Build

# Test database (SQLite file-based for stability)
TEST_DB_PATH = "test_poe2li.db"
TEST_ENGINE = create_engine(
    f"sqlite:///{TEST_DB_PATH}",
    connect_args={"check_same_thread": False},
)
TestSession = sessionmaker(autocommit=False, autoflush=False, bind=TEST_ENGINE)


def override_get_db():
    db = TestSession()
    try:
        yield db
    finally:
        db.close()


VALID_POB_CODE = "eNqtW9t34jYTf27_Cg7PJPH90pO0hwBJaHOhQJLdfekRtgB_ETZryyT0r_9Gkm1srnLSfWBteX4zo5FmNCMpl398LEhjheMkiMKrpnquNBs49CI_CGdXzefxzZnT_OP3Xy8HiM6fptdpQNgX7fdff7nkLw2PoCR5RAt81RyicIbjZgMlHg79zubDYxTiZsOboxh5FMf3eIVJO6XRQ-TDVxqn8HUV4Hfx3n8YPA3HzcYCBeEo8t4wvY2jdAnKNRsUxTNMX3J1lX-gjTB2V03LaIJWv1wOCFrjeEQRbawQSYGhcu5oqqaYzUYCrVfNNnQXzXAXLeC3eVEPdZ3GCT0BVc9tR8txoyXG_kHSgv0gxr3pFHs0WOFOHNDOHIXeYRH6uVtAJci1Mu1DSmiwJAGM1SF6280Bdyd5q-eGpeuOras5ZhxRRLqD0WHbVikjWoP5a0Dn1wRsekzAflh_FgYU18cNoiCJwlodkiLupISAN0nRDnGC4xWiwXFFdjvQiRaTIDxurkLKAwpRJ0qoHOUAx-DptBZghL0IgkNdGTWR98EUy1PW6kcGqKvN5_rRG8nS1Wb8OYWGEPfkKEdRSo5Saq5R0NLDoUi3c6ou_jhMVQSsfiihXBevIuZKEg4dB5OUHo5-jmGfq6atmKqiGoZRiQO9u8FhR1VNvYj983USeIg8oI9gkS4g5I7RGz6snG25m6k1m9MQgsgnsDdBjD8B60TEl4WVewnLSJTIAi2lFAWC8A6FftvzUkgg1hKji-K3ECeJbFSF4HgKUe4Ic-fTCzqs-95vjLQfetJsn8M400gaMgTvZanJhBxZohVlv5QsCMiFsCGe4TATt5aD3GPszW9hAIfoiA_pm2yJhXyJ2MJsy0iP2XaLq4xpFWU_4pSZVPvcKiNrWopB5CxV0nC0DCCXk6es1_9tjPRE6YU4nq1H8wATvx51bq8OWh4OQ05lCpThx6bCAXm1BqkMlRusyqIpJ03diFuh5NgCZWxZQpDLGWGFfHwiqd_MTQy5di3EII7-x-oYUg8G3SCkPuKT0rp4ShgsYkMIy6c0QlZAO15EaSwZygSx1ODluYIoQYfYTz25RKaoLq8JFNWy3ShQ3Ni1oG1KkffWjfxZvRGthajqN0qXS4hYzBNOMDgzlXIaBHlAIJPUbmifwI-PRaqSAJYwyQrY0NYQUCSBslK2AKdEKZUUTrorG-JTAtRzxdgZ0QcIlQtYc_gGykN0eDUxSnsoCYZRHyI_SJMHTOFdYkyhCpcqjjmhZGk_iN6hy3O2XXVYBX0fNWTIEqrEOPx3Lc2_Qi4loBf6kGyDLaVlbCM2Yq7T6TRpeNFigug9zIarZrMxgbb8GdL6BGcvAjEOFrDsJEkXUdTws1rtBcUBCqnKNwK3GjXemGAUe3PG6QYRMoHow9hvWjP-lxd865I9PUYUJ0wka81fLjtROA1mDSQ24_jLCFMmgmtXtDQCP2_kpvHwHNwXx40wXUxwzHUK-Q7oothy6wYwv2E4aHuxiFg4yeb1AQZKzsHHiyi8ieLFiEXV5BjILkA4xIt1tlJEhPAN2qPicmBnHkA0PSnJrErajqQHQBXM9uallKDtiCoF2hsl9yO3pG1Hvf0g1zL3yyvvFstBWf_qo5j5T6N0x9rt3WnYnqk8omkYYpa3w3Qm6-PzWNnFd9KYOcJuxXBA8f3WHeS7CDIoZthaAGbTEwBHsaqYcup3yq3ZzlvAAlkniuN0yVLRTrwGzyti7gEO5q492VY1hBaf-20nSmHpxGR6lItqV6dQpeqQngivEGDj9XMiNxd0ZScA1Jh-ozmkoKcj07ZvVNPmY0htVz0GfMWI7xCdFr3FoAth41R4K3qXBLOAPE15PiAxCQqjeBEscTIrQ1W30tlU_QXsFn6g4jq5hrFtmLLjsuO6bJ2_KJZSviyLN_Y4jjF-CfB7498oWtyLAz4oeNnbt6umZZ67FkxdzdJ12zBF-3eeEuvnlmuyzVhD0VlqMo_eWbaSK-3hJD9wFGnBiMZ5VtBfLKOYNvAH-2-AYrq-ak4RScTIcZWylIDVbEU2wF7EKWjf5wdtYeQzKZplO1bL1F1LaWmOYbc0VdetlmHpqtOyFFCyZenQhZZpubrZ0hUFaAzXcq2W7tiK3VJVzXBapqFqdks3VMCqlgHMLNvWWqZiaS40gxng14BvQKKCDM1RWobhAInuqIbeAjvYINsBc7U0wwQaVdFsHVpAhRYwcYyW7toqKKmZBvA1TLeluYYNv4ajmS1gYiigngstpmWZast0VIV9dYGXAx0wDFvXQVHFdVn3TAe6oWlKyzFcvWXBV4CopqWCNMN1WrqmG6C65loG01EHclMDfVXHcbSWAcoBSxhXsINimmAZF7rQMm2mo-nqtgWiDR166do6cDAtx2FK6i3VdKGThmVp0GDawExTVBVaHFAKTAOUYHjLAZaGwrTUFFAbugD9sCwYFc1SwfomGJGR2yDbNDSmE0QTGBtHddmmCz8tQfG6vTnmZiMfBiQ_-gZ3X_dDiuMQEfapciTOGsALKZvhm3Nsk513JwBZi_on4Ykxpy8x0rJc83l4zx9-mVO6TH67uHh_fz9fIjqPpvgjIPgcku2LJYBhsp4lb5DLnTF5F234dz3rt8daECjJ7P5OffxOn-zkdTpb6Atf_eb0Z-Tfh9h5fFzNX-bt8fVS-fBe757-VrXH28dx_y-3TwZnfvpqDL7ZTtR_1UbuLJjczf735K392dl41sN_D_zR2b3bmSR3_Z-Wq6hP6k1y3euPdFt1yNLt_Hn27Xu3RwY_37Ve2FmuOj-N0J8s7vQ5VAXv3zS7M4xodP3j7eyH_f1tgH48vdm6_dLr0u735796t6u_Js_dnz_I-D58GdtqO74-m3zcQteuuHEucutcitsDSRabWBEaB77I9-G9Tak428k_QFHx8SiclxU1cfYs5p9wCTEjhWOIWSHcQ_hz7iQbfxauUvZnMQ1LflN2auFCfF6LWZh5Nfde4UncqSruxLw_83vuNcL7xcwVXiN8SviXiAoiOHGvER5R9hruF8JpRIQSTi2cRsQN4TUirHEfyxyTO40IJyJk8fjXbAQhzS2bjcZFZTguL1gY5YsAi7PsYcSmbQJjMkWw9tzifBkIoQYqjsqaeURmxFmNVoL8nSISsDjOnTOBuA6NyfUaSvhiGSg33rActHpkLpaQdLkUdOP1kvWifX8vvtzjGfLWjEG-WIhFIdMnqxBF1Sl6xJcaCoBji5PoFSPLO5UmWJzTQiKyjELezHrFxWWEmbSDtA0aUIL5ViYzULPsJX0f3IavXTzQQHDPV-0_8TsmDdESgKDBBCg3AzkiEeXtWWAToBsIXW-N-ghtP2KfiixYb-komiQZ8JW1yiBrktZZ2LdWN9uQSWFaA3CHyaIWIFNKqwG5jvx1Iytb5FG3JFpBglpHTETr0A-hGqplXA7Q6gL0GgDw91oCGH2t6REvavFn9HX4s825Ra0eC4RWG1FHq2tMPjPDG6N3tPyEux7CXV5kgZSHax6k-XYgIp5YpfrhMqV7qjYW2P8RzRknQQlJBL9H2bu56XXG_ZdeUU4FifcP2wNlVx4zyEicRzW8iBC0hGI6X1F4WM9WFHYEBStPOkkE9VWTlUn8YxdTFJBEittdUXNXeHE-d9V6_AQnXvsHLAyUGfWglnrP9iKonErsFuCuMkITdmjK9oTlLMWL2gorcRTVgQS7dGB7nAur-6tMWItcV6CSRGTLtFmb9FCzREMYb9colCUhkC8F08CTN_DmJmfVNtVrNcd58IuXVbxokgGLa5RVdNYmZVV-e3PLqqJNan5hD62raNEkAy4O_KsMiuYovCvuYhzn1CO4HRB2rrU1so9RyCc7BIyCQIbhA4SSrGasMnxiu4H5FxlORUGU7HhP3i5lK3Y9qmqmzYWpE31ht38q0NJ9oFNeH-x4bOWKzIlhKW9CV0PZ7oWW46yyk4IKE9EmOQxZHlYZgvJtghM9ybZwq52o3CY54Sg85LZXUeDvRovtj19myK8U_Ad6sUsD_wGb4lqIFC9es2x5S9Z2EC4KvEPoZxqwivVrTJi_fY0Dc7uvceBJoBR6uJOGDI8mHxtkfja9I3iGk0_ji3PsT3MQp-2fhvPNf-nQDzOW7xzsif3Fp6_xYsd8XTDJca_YdOqEVhKxQ56XWChrdVT4v7h9vCe0la8lf4URLON3svniQU7FXZg7jAj7O5SIfI3h_uvXR4fgIC92mTFdotDPuT3VydIPWy-iCTDlVzS67NJk8iUte_wMbsPn8iIv5y75GU9jNI_e2_6Kzcgx2LfYx2v4OKFBiLIFmLDd_eUSh37pVOjyYufv4v4PueqFEw=="


@pytest.fixture(scope="module", autouse=True)
def setup_db():
    """Set up test database."""
    # Create tables
    Base.metadata.create_all(bind=TEST_ENGINE)
    yield
    # Cleanup
    Base.metadata.drop_all(bind=TEST_ENGINE)
    try:
        if os.path.exists(TEST_DB_PATH):
            os.remove(TEST_DB_PATH)
    except PermissionError:
        pass  # Windows file lock, ignore


@pytest.fixture(scope="module")
def client():
    """Create a test client."""
    from app.main import app

    # Override dependency
    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as c:
        yield c

    app.dependency_overrides.clear()


def test_save_and_retrieve_build(client):
    """POST /api/builds saves a build, GET /api/builds/{id} retrieves it."""
    # Save
    save_resp = client.post("/api/builds", json={"pob_code": VALID_POB_CODE})
    assert save_resp.status_code == 200
    data = save_resp.json()
    build_id = data["id"]
    assert build_id is not None
    assert data["status"] == "done"
    assert data["build"]["className"] == "Ranger"

    # Retrieve
    get_resp = client.get(f"/api/builds/{build_id}")
    assert get_resp.status_code == 200
    retrieved = get_resp.json()
    assert retrieved["id"] == build_id
    assert retrieved["build"]["build"]["className"] == "Ranger"
    assert retrieved["homework"] is not None
    assert "core_idea" in retrieved["homework"]


def test_get_nonexistent_build_returns_404(client):
    """GET /api/builds/999 returns 404."""
    resp = client.get("/api/builds/999")
    assert resp.status_code == 404


def test_list_builds(client):
    """GET /api/builds returns a list."""
    resp = client.get("/api/builds")
    assert resp.status_code == 200
    builds = resp.json()
    assert isinstance(builds, list)
    assert len(builds) >= 1
