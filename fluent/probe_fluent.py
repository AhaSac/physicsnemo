"""Launch the pinned Fluent 2024 R2 installation and inspect workflow defaults."""
import json
from pathlib import Path
import ansys.fluent.core as pyfluent

out = Path(__file__).parent.resolve() / 'outputs' / 'probe'
out.mkdir(parents=True, exist_ok=True)
session = pyfluent.launch_fluent(
    fluent_path=r'C:\Program Files\ANSYS Inc\v242\fluent\ntbin\win64\fluent.exe',
    product_version='24.2.0', mode='meshing', precision='double',
    processor_count=4, ui_mode='no_gui', start_timeout=120,
    cwd=str(out), start_watchdog=False)
try:
    print('VERSION', session.get_fluent_version(), flush=True)
    session.workflow.InitializeWorkflow(WorkflowType='Watertight Geometry')
    task = session.workflow.TaskObject
    for name in ('Import Geometry', 'Generate the Surface Mesh', 'Describe Geometry',
                 'Generate the Volume Mesh'):
        print(name, task[name].Arguments.get_state(), flush=True)
    print('UTILS', [n for n in dir(session.meshing_utilities) if 'quality' in n or 'zone' in n or 'count' in n], flush=True)
    session.workflow.TaskObject['Import Geometry'].Arguments.set_state({
        'FileName': r'C:\Users\AhaSac\Desktop\pump\0907wang\xt\imperfectimpeller\3impeller.scdoc',
        'LengthUnit': 'mm'})
    task['Import Geometry'].Execute()
    print('IMPORTED', flush=True)
    print('SURFACE_DEFAULTS', task['Generate the Surface Mesh'].Arguments.get_state(), flush=True)
    task['Generate the Surface Mesh'].Arguments.set_state({'CFDSurfaceMeshControls': {'MinSize': 0.3, 'MaxSize': 2.0, 'GrowthRate': 1.15, 'CurvatureNormalAngle': 12.0}})
    task['Generate the Surface Mesh'].Execute()
    print('FACE_QUALITY', session.meshing_utilities.get_face_quality_limits(face_zone_name_pattern='*', measure='Skewness'), flush=True)
    print('FACE_ZONES', session.meshing_utilities.get_face_zones(filter='*'), flush=True)
    session.tui.file.write_mesh(str(out / 'surface.msh.h5'))
    task['Describe Geometry'].UpdateChildTasks(SetupTypeChanged=False)
    task['Describe Geometry'].Arguments.set_state({'SetupType': 'The geometry consists of only fluid regions with no voids'})
    task['Describe Geometry'].UpdateChildTasks(SetupTypeChanged=True)
    task['Describe Geometry'].Execute()
    task['Update Boundaries'].Execute()
    task['Update Regions'].Execute()
    task['Add Boundary Layers'].Arguments.set_state({'AddChild': 'no'})
    task['Add Boundary Layers'].AddChildAndUpdate(DeferUpdate=False)
    task['Generate the Volume Mesh'].Arguments.set_state({'VolumeFill': 'polyhedra'})
    task['Generate the Volume Mesh'].Execute()
    print('CELL_QUALITY', session.meshing_utilities.get_cell_quality_limits(cell_zone_name_pattern='*', measure='Orthogonal Quality'), flush=True)
    print('CELL_COUNT', session.meshing_utilities.get_cell_zone_count(cell_zone_name_pattern='*'), flush=True)
    session.tui.mesh.check_mesh()
    session.tui.file.write_mesh(str(out / 'volume.msh.h5'))
    (out / 'fluent_import.json').write_text(json.dumps({'version': str(session.get_fluent_version()), 'imported': True}), encoding='utf-8')
finally:
    session.exit()
