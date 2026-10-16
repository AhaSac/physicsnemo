import json
from pathlib import Path
import ansys.fluent.core as p

out = Path(__file__).resolve().parent / 'outputs/probe'
s = p.launch_fluent(fluent_path=r'C:\Program Files\ANSYS Inc\v242\fluent\ntbin\win64\fluent.exe', product_version='24.2.0',
                    mode='meshing', precision='double', processor_count=4,
                    ui_mode='no_gui', cwd=str(out), start_timeout=120, start_watchdog=False)
try:
    s.tui.file.read_mesh(str(out / 'volume.msh.h5'))
    u = s.meshing_utilities
    print('OBJECTS', u.get_objects(type_name='mesh'), flush=True)
    zones = u.get_face_zones(filter='*')
    print('NAMES', u.convert_zone_ids_to_name_strings(zone_id_list=zones), flush=True)
    print('BEFORE_FACES', u.get_face_quality_limits(face_zone_name_pattern='*', measure='Skewness'), flush=True)
    print('IMPROVE_DEFAULT', s.meshing.ImproveVolumeMesh.create_instance().get_state(), flush=True)
    print('RESULT', s.meshing.ImproveVolumeMesh(CellQualityLimit=0.35), flush=True)
    print('AFTER_CELLS', u.get_cell_quality_limits(cell_zone_name_pattern='*', measure='Orthogonal Quality'), flush=True)
    s.tui.file.write_mesh(str(out / 'volume_improved.msh.h5'))
finally:
    s.exit()
