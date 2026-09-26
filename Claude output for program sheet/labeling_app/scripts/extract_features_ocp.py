#!/usr/bin/env python3
"""Extract STEP B-Rep features using OCP OpenCascade bindings."""

from __future__ import annotations

import json
import math
from pathlib import Path
import sys

from OCP.Bnd import Bnd_Box
from OCP.BRep import BRep_Tool
from OCP.BRepAdaptor import BRepAdaptor_Curve, BRepAdaptor_Surface
from OCP.BRepBndLib import BRepBndLib
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepGProp import BRepGProp
from OCP.BRepMesh import BRepMesh_IncrementalMesh
from OCP.GProp import GProp_GProps
from OCP.GeomAbs import (
    GeomAbs_BezierCurve,
    GeomAbs_BezierSurface,
    GeomAbs_BSplineCurve,
    GeomAbs_BSplineSurface,
    GeomAbs_Circle,
    GeomAbs_Cone,
    GeomAbs_Cylinder,
    GeomAbs_Ellipse,
    GeomAbs_Hyperbola,
    GeomAbs_Line,
    GeomAbs_OffsetCurve,
    GeomAbs_OffsetSurface,
    GeomAbs_OtherCurve,
    GeomAbs_OtherSurface,
    GeomAbs_Parabola,
    GeomAbs_Plane,
    GeomAbs_Sphere,
    GeomAbs_SurfaceOfExtrusion,
    GeomAbs_SurfaceOfRevolution,
    GeomAbs_Torus,
)
from OCP.IFSelect import IFSelect_RetDone
from OCP.STEPControl import STEPControl_Reader
from OCP.TopAbs import (
    TopAbs_COMPOUND,
    TopAbs_COMPSOLID,
    TopAbs_EDGE,
    TopAbs_EXTERNAL,
    TopAbs_FACE,
    TopAbs_FORWARD,
    TopAbs_INTERNAL,
    TopAbs_REVERSED,
    TopAbs_SHELL,
    TopAbs_SOLID,
    TopAbs_VERTEX,
    TopAbs_WIRE,
)
from OCP.TopExp import TopExp, TopExp_Explorer
from OCP.TopLoc import TopLoc_Location
from OCP.TopoDS import TopoDS
from OCP.TopTools import TopTools_IndexedMapOfShape


SURFACE_TYPE_MAP = {
    GeomAbs_Plane: "Plane",
    GeomAbs_Cylinder: "Cylinder",
    GeomAbs_Cone: "Cone",
    GeomAbs_Sphere: "Sphere",
    GeomAbs_Torus: "Torus",
    GeomAbs_BezierSurface: "Bezier",
    GeomAbs_BSplineSurface: "BSpline",
    GeomAbs_SurfaceOfRevolution: "SurfaceOfRevolution",
    GeomAbs_SurfaceOfExtrusion: "SurfaceOfExtrusion",
    GeomAbs_OffsetSurface: "Offset",
    GeomAbs_OtherSurface: "Other",
}

CURVE_TYPE_MAP = {
    GeomAbs_Line: "Line",
    GeomAbs_Circle: "Circle",
    GeomAbs_Ellipse: "Ellipse",
    GeomAbs_Hyperbola: "Hyperbola",
    GeomAbs_Parabola: "Parabola",
    GeomAbs_BezierCurve: "Bezier",
    GeomAbs_BSplineCurve: "BSpline",
    GeomAbs_OffsetCurve: "Offset",
    GeomAbs_OtherCurve: "Other",
}

ORIENTATION_MAP = {
    TopAbs_FORWARD: "Forward",
    TopAbs_REVERSED: "Reversed",
    TopAbs_INTERNAL: "Internal",
    TopAbs_EXTERNAL: "External",
}


def rounded(value: float, digits: int = 6) -> float:
    return round(float(value), digits)


def vec_sub(a: tuple[float, float, float], b: tuple[float, float, float]) -> tuple[float, float, float]:
    return a[0] - b[0], a[1] - b[1], a[2] - b[2]


def vec_cross(a: tuple[float, float, float], b: tuple[float, float, float]) -> tuple[float, float, float]:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def vec_dot(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def vec_norm(a: tuple[float, float, float]) -> float:
    return math.sqrt(vec_dot(a, a))


def vec_unit(a: tuple[float, float, float]) -> tuple[float, float, float]:
    norm = vec_norm(a)
    if norm <= 1e-12:
        return 0.0, 0.0, 1.0
    return a[0] / norm, a[1] / norm, a[2] / norm


def point_tuple(point) -> tuple[float, float, float]:
    return float(point.X()), float(point.Y()), float(point.Z())


def transform_point(point, location) -> tuple[float, float, float]:
    if location.IsIdentity():
        return point_tuple(point)
    return point_tuple(point.Transformed(location.Transformation()))


def load_step(filename: str):
    reader = STEPControl_Reader()
    status = reader.ReadFile(filename)
    if status != IFSelect_RetDone:
        raise RuntimeError(f"Failed to read STEP file: {filename}")
    reader.TransferRoots()
    return reader.OneShape()


def iter_shapes(shape, topo_type):
    explorer = TopExp_Explorer(shape, topo_type)
    while explorer.More():
        yield explorer.Current()
        explorer.Next()


def count_shapes(shape) -> dict[str, int]:
    counts = {}
    for topo_type, name in [
        (TopAbs_COMPOUND, "Compounds"),
        (TopAbs_COMPSOLID, "CompSolids"),
        (TopAbs_SOLID, "Solids"),
        (TopAbs_SHELL, "Shells"),
        (TopAbs_FACE, "Faces"),
        (TopAbs_WIRE, "Wires"),
        (TopAbs_EDGE, "Edges"),
        (TopAbs_VERTEX, "Vertices"),
    ]:
        mapped = TopTools_IndexedMapOfShape()
        TopExp.MapShapes_s(shape, topo_type, mapped)
        counts[name] = mapped.Size()
    return counts


def get_bounding_box(shape) -> dict[str, float]:
    bbox = Bnd_Box()
    BRepBndLib.Add_s(shape, bbox)
    xmin, ymin, zmin, xmax, ymax, zmax = bbox.Get()
    dx, dy, dz = xmax - xmin, ymax - ymin, zmax - zmin
    return {
        "xmin": rounded(xmin),
        "ymin": rounded(ymin),
        "zmin": rounded(zmin),
        "xmax": rounded(xmax),
        "ymax": rounded(ymax),
        "zmax": rounded(zmax),
        "length_x": rounded(dx),
        "length_y": rounded(dy),
        "length_z": rounded(dz),
        "diagonal": rounded(math.sqrt(dx * dx + dy * dy + dz * dz)),
    }


def get_mass_properties(shape) -> dict[str, object]:
    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, props)
    cog = props.CentreOfMass()
    matrix = props.MatrixOfInertia()
    return {
        "volume": rounded(props.Mass()),
        "center_of_mass": {"x": rounded(cog.X()), "y": rounded(cog.Y()), "z": rounded(cog.Z())},
        "matrix_of_inertia": [
            [rounded(matrix.Value(i, j)) for j in range(1, 4)]
            for i in range(1, 4)
        ],
    }


def get_surface_area(shape) -> float:
    props = GProp_GProps()
    BRepGProp.SurfaceProperties_s(shape, props)
    return rounded(props.Mass())


def analyze_faces(shape) -> dict[str, object]:
    faces_data = []
    surface_type_counts: dict[str, int] = {}
    total_area = 0.0

    for raw_face in iter_shapes(shape, TopAbs_FACE):
        face = TopoDS.Face_s(raw_face)
        surf = BRepAdaptor_Surface(face, True)
        surf_type = SURFACE_TYPE_MAP.get(surf.GetType(), "Unknown")
        surface_type_counts[surf_type] = surface_type_counts.get(surf_type, 0) + 1

        props = GProp_GProps()
        BRepGProp.SurfaceProperties_s(face, props)
        area = rounded(props.Mass())
        centroid = props.CentreOfMass()
        total_area += area

        face_info: dict[str, object] = {
            "surface_type": surf_type,
            "area": area,
            "orientation": ORIENTATION_MAP.get(face.Orientation(), "Unknown"),
            "centroid": {
                "x": rounded(centroid.X()),
                "y": rounded(centroid.Y()),
                "z": rounded(centroid.Z()),
            },
        }

        if surf_type == "Plane":
            plane = surf.Plane()
            normal = plane.Axis().Direction()
            origin = plane.Location()
            face_info["plane"] = {
                "origin": {"x": rounded(origin.X()), "y": rounded(origin.Y()), "z": rounded(origin.Z())},
                "normal": {"x": rounded(normal.X()), "y": rounded(normal.Y()), "z": rounded(normal.Z())},
            }
        elif surf_type == "Cylinder":
            cyl = surf.Cylinder()
            face_info["cylinder"] = {
                "radius": rounded(cyl.Radius()),
                "axis_direction": {
                    "x": rounded(cyl.Axis().Direction().X()),
                    "y": rounded(cyl.Axis().Direction().Y()),
                    "z": rounded(cyl.Axis().Direction().Z()),
                },
                "axis_location": {
                    "x": rounded(cyl.Location().X()),
                    "y": rounded(cyl.Location().Y()),
                    "z": rounded(cyl.Location().Z()),
                },
            }
        elif surf_type == "Cone":
            cone = surf.Cone()
            face_info["cone"] = {
                "semi_angle_deg": rounded(math.degrees(cone.SemiAngle())),
                "apex": {
                    "x": rounded(cone.Apex().X()),
                    "y": rounded(cone.Apex().Y()),
                    "z": rounded(cone.Apex().Z()),
                },
                "axis_direction": {
                    "x": rounded(cone.Axis().Direction().X()),
                    "y": rounded(cone.Axis().Direction().Y()),
                    "z": rounded(cone.Axis().Direction().Z()),
                },
                "axis_location": {
                    "x": rounded(cone.Location().X()),
                    "y": rounded(cone.Location().Y()),
                    "z": rounded(cone.Location().Z()),
                },
            }
        elif surf_type == "Sphere":
            sphere = surf.Sphere()
            face_info["sphere"] = {
                "radius": rounded(sphere.Radius()),
                "center": {
                    "x": rounded(sphere.Location().X()),
                    "y": rounded(sphere.Location().Y()),
                    "z": rounded(sphere.Location().Z()),
                },
            }
        elif surf_type == "Torus":
            torus = surf.Torus()
            face_info["torus"] = {
                "major_radius": rounded(torus.MajorRadius()),
                "minor_radius": rounded(torus.MinorRadius()),
            }

        faces_data.append(face_info)

    return {
        "total_faces": len(faces_data),
        "total_area": rounded(total_area),
        "surface_type_counts": surface_type_counts,
        "faces": faces_data,
    }


def extract_mesh_data(
    shape,
    *,
    linear_deflection: float = 0.5,
    angular_deflection: float = 0.5,
) -> dict[str, object]:
    """Extract real OCP triangulation as mesh-level graph data."""
    mesh = BRepMesh_IncrementalMesh(shape, linear_deflection, False, angular_deflection, True)
    mesh.Perform()

    facets: list[dict[str, object]] = []
    face_to_facets: dict[str, list[int]] = {}
    face_normal_acc: dict[int, list[float]] = {}
    edge_to_facets: dict[tuple[tuple[float, float, float], tuple[float, float, float]], list[int]] = {}

    for face_index, raw_face in enumerate(iter_shapes(shape, TopAbs_FACE)):
        face = TopoDS.Face_s(raw_face)
        loc = TopLoc_Location()
        triangulation = BRep_Tool.Triangulation_s(face, loc)
        if triangulation is None:
            continue

        face_to_facets[str(face_index)] = []
        node_cache = {
            node_index: transform_point(triangulation.Node(node_index), loc)
            for node_index in range(1, triangulation.NbNodes() + 1)
        }

        for tri_index in range(1, triangulation.NbTriangles() + 1):
            n1, n2, n3 = triangulation.Triangle(tri_index).Get()
            p1, p2, p3 = node_cache[n1], node_cache[n2], node_cache[n3]
            cross = vec_cross(vec_sub(p2, p1), vec_sub(p3, p1))
            area2 = vec_norm(cross)
            normal = vec_unit(cross)
            if face.Orientation() == TopAbs_REVERSED:
                normal = (-normal[0], -normal[1], -normal[2])
            centroid = (
                (p1[0] + p2[0] + p3[0]) / 3.0,
                (p1[1] + p2[1] + p3[1]) / 3.0,
                (p1[2] + p2[2] + p3[2]) / 3.0,
            )
            d_coeff = -vec_dot(normal, centroid)
            facet_index = len(facets)
            facets.append(
                {
                    "face_index": face_index,
                    "normal": {"x": rounded(normal[0]), "y": rounded(normal[1]), "z": rounded(normal[2])},
                    "d": rounded(d_coeff),
                    "area": rounded(area2 * 0.5),
                }
            )
            face_to_facets[str(face_index)].append(facet_index)

            acc = face_normal_acc.setdefault(face_index, [0.0, 0.0, 0.0])
            acc[0] += normal[0] * area2
            acc[1] += normal[1] * area2
            acc[2] += normal[2] * area2

            vertices = [p1, p2, p3]
            for left, right in ((vertices[0], vertices[1]), (vertices[1], vertices[2]), (vertices[2], vertices[0])):
                key = tuple(sorted((tuple(round(v, 5) for v in left), tuple(round(v, 5) for v in right))))
                edge_to_facets.setdefault(key, []).append(facet_index)

    adjacency = {index: set() for index in range(len(facets))}
    for adjacent_facets in edge_to_facets.values():
        if len(adjacent_facets) < 2:
            continue
        for left in adjacent_facets:
            for right in adjacent_facets:
                if left != right:
                    adjacency[left].add(right)

    face_normals = {}
    for face_index, acc in face_normal_acc.items():
        normal = vec_unit((acc[0], acc[1], acc[2]))
        face_normals[str(face_index)] = {"x": rounded(normal[0]), "y": rounded(normal[1]), "z": rounded(normal[2])}

    return {
        "mesher_done": bool(mesh.IsDone()),
        "linear_deflection": linear_deflection,
        "angular_deflection": angular_deflection,
        "total_facets": len(facets),
        "facets": facets,
        "facet_adjacency": {str(index): sorted(values) for index, values in adjacency.items()},
        "face_to_facets": face_to_facets,
        "face_normals": face_normals,
    }


def analyze_edges(shape) -> dict[str, object]:
    edges_data = []
    curve_type_counts: dict[str, int] = {}
    total_length = 0.0

    for raw_edge in iter_shapes(shape, TopAbs_EDGE):
        edge = TopoDS.Edge_s(raw_edge)
        curve = BRepAdaptor_Curve(edge)
        curve_type = CURVE_TYPE_MAP.get(curve.GetType(), "Unknown")
        curve_type_counts[curve_type] = curve_type_counts.get(curve_type, 0) + 1

        props = GProp_GProps()
        BRepGProp.LinearProperties_s(edge, props)
        length = rounded(props.Mass())
        total_length += length

        edge_info: dict[str, object] = {
            "curve_type": curve_type,
            "length": length,
            "orientation": ORIENTATION_MAP.get(edge.Orientation(), "Unknown"),
        }

        if curve_type == "Circle":
            circle = curve.Circle()
            edge_info["circle"] = {
                "radius": rounded(circle.Radius()),
                "center": {
                    "x": rounded(circle.Location().X()),
                    "y": rounded(circle.Location().Y()),
                    "z": rounded(circle.Location().Z()),
                },
                "normal": {
                    "x": rounded(circle.Axis().Direction().X()),
                    "y": rounded(circle.Axis().Direction().Y()),
                    "z": rounded(circle.Axis().Direction().Z()),
                },
            }
        elif curve_type == "Line":
            line = curve.Line()
            edge_info["line"] = {
                "direction": {
                    "x": rounded(line.Direction().X()),
                    "y": rounded(line.Direction().Y()),
                    "z": rounded(line.Direction().Z()),
                },
                "location": {
                    "x": rounded(line.Location().X()),
                    "y": rounded(line.Location().Y()),
                    "z": rounded(line.Location().Z()),
                },
            }

        edges_data.append(edge_info)

    return {
        "total_edges": len(edges_data),
        "total_length": rounded(total_length),
        "curve_type_counts": curve_type_counts,
        "edges": edges_data,
    }


def analyze_vertices(shape) -> dict[str, object]:
    vertices = []
    seen = set()
    for raw_vertex in iter_shapes(shape, TopAbs_VERTEX):
        vertex = TopoDS.Vertex_s(raw_vertex)
        point = BRep_Tool.Pnt_s(vertex)
        key = (round(point.X(), 4), round(point.Y(), 4), round(point.Z(), 4))
        if key in seen:
            continue
        seen.add(key)
        vertices.append({"x": rounded(point.X()), "y": rounded(point.Y()), "z": rounded(point.Z())})
    return {"total_unique_vertices": len(vertices), "vertices": vertices}


def detect_holes(face_data: dict[str, object]) -> list[dict[str, object]]:
    holes = []
    for index, face in enumerate(face_data["faces"]):
        if face["surface_type"] != "Cylinder":
            continue
        cylinder = face.get("cylinder", {})
        radius = cylinder.get("radius", 0.0)
        holes.append(
            {
                "face_index": index,
                "radius": radius,
                "diameter": rounded(radius * 2.0),
                "axis_direction": cylinder.get("axis_direction"),
                "axis_location": cylinder.get("axis_location"),
            }
        )
    return holes


def extract_face_adjacency(shape) -> dict[int, list[int]]:
    edge_map = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(shape, TopAbs_EDGE, edge_map)
    faces = [TopoDS.Face_s(face) for face in iter_shapes(shape, TopAbs_FACE)]

    edge_to_faces: dict[int, list[int]] = {}
    for face_index, face in enumerate(faces):
        for raw_edge in iter_shapes(face, TopAbs_EDGE):
            edge_index = edge_map.FindIndex(raw_edge)
            edge_to_faces.setdefault(edge_index, []).append(face_index)

    adjacency = {index: set() for index in range(len(faces))}
    for face_indices in edge_to_faces.values():
        if len(face_indices) != 2:
            continue
        left, right = face_indices
        adjacency[left].add(right)
        adjacency[right].add(left)

    return {index: sorted(neighbours) for index, neighbours in adjacency.items()}


def extract_face_edge_relations(shape, face_data: dict[str, object], mesh_data: dict[str, object]) -> list[dict[str, object]]:
    """Classify B-Rep face adjacency into model relation channels."""
    edge_map = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(shape, TopAbs_EDGE, edge_map)
    faces = [TopoDS.Face_s(face) for face in iter_shapes(shape, TopAbs_FACE)]

    edge_to_faces: dict[int, list[int]] = {}
    for face_index, face in enumerate(faces):
        for raw_edge in iter_shapes(face, TopAbs_EDGE):
            edge_index = edge_map.FindIndex(raw_edge)
            edge_to_faces.setdefault(edge_index, []).append(face_index)

    face_normals = mesh_data.get("face_normals", {})
    faces_json = face_data["faces"]
    relations: list[dict[str, object]] = []

    for edge_index, face_indices in edge_to_faces.items():
        if len(face_indices) != 2:
            continue
        left, right = face_indices
        edge = TopoDS.Edge_s(edge_map.FindKey(edge_index))
        try:
            continuity = BRep_Tool.Continuity_s(edge, faces[left], faces[right])
            continuity_value = int(continuity)
        except Exception:
            continuity_value = 0

        left_normal_raw = face_normals.get(str(left), {"x": 0.0, "y": 0.0, "z": 1.0})
        right_normal_raw = face_normals.get(str(right), {"x": 0.0, "y": 0.0, "z": 1.0})
        left_normal = (left_normal_raw["x"], left_normal_raw["y"], left_normal_raw["z"])
        right_normal = (right_normal_raw["x"], right_normal_raw["y"], right_normal_raw["z"])
        normal_dot = vec_dot(left_normal, right_normal)

        if continuity_value >= 1 or abs(normal_dot) > 0.985:
            relation = "smooth"
        else:
            left_centroid = faces_json[left].get("centroid", {"x": 0.0, "y": 0.0, "z": 0.0})
            right_centroid = faces_json[right].get("centroid", {"x": 0.0, "y": 0.0, "z": 0.0})
            c_left = (left_centroid["x"], left_centroid["y"], left_centroid["z"])
            c_right = (right_centroid["x"], right_centroid["y"], right_centroid["z"])
            lr = vec_sub(c_right, c_left)
            rl = vec_sub(c_left, c_right)
            # For outward normals, adjacent exterior faces usually see each other
            # behind both normals. Interior pocket edges tend to violate this.
            relation = "convex" if vec_dot(lr, left_normal) < 0 and vec_dot(rl, right_normal) < 0 else "concave"

        for source, target in ((left, right), (right, left)):
            relations.append(
                {
                    "source": source,
                    "target": target,
                    "edge_index": edge_index,
                    "relation": relation,
                    "continuity": continuity_value,
                    "normal_dot": rounded(normal_dot),
                }
            )

    return relations


def check_validity(shape) -> bool:
    return bool(BRepCheck_Analyzer(shape).IsValid())


def extract_features(step_file: str | Path) -> dict[str, object]:
    step_path = Path(step_file).expanduser().resolve()
    shape = load_step(str(step_path))
    topology_counts = count_shapes(shape)
    face_data = analyze_faces(shape)
    mesh_data = extract_mesh_data(shape)
    return {
        "file": str(step_path),
        "topology_counts": topology_counts,
        "bounding_box": get_bounding_box(shape),
        "mass_properties": get_mass_properties(shape),
        "surface_area": get_surface_area(shape),
        "faces": face_data,
        "edges": analyze_edges(shape),
        "vertices": analyze_vertices(shape),
        "holes_detected": detect_holes(face_data),
        "is_valid": check_validity(shape),
        "face_adjacency": extract_face_adjacency(shape),
        "face_edge_relations": extract_face_edge_relations(shape, face_data, mesh_data),
        "mesh": mesh_data,
    }


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: python extract_features_ocp.py <step_file> [output_json]")
        return 2

    step_file = Path(sys.argv[1]).expanduser()
    output = Path(sys.argv[2]).expanduser() if len(sys.argv) > 2 else step_file.with_suffix(".features.json")
    if not step_file.exists():
        print(f"ERROR: file not found: {step_file}", file=sys.stderr)
        return 2

    data = extract_features(step_file)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(data, indent=2) + "\n")

    faces = data["faces"]
    print(
        f"OCP extracted: {faces['total_faces']} faces, {data['edges']['total_edges']} edges, "
        f"{data['mesh']['total_facets']} mesh facets"
    )
    print(f"Output: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
