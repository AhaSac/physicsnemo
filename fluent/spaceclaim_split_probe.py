# Python Script, API Version = V242
"""Split detached modeler copies only; never save or modify the source document."""
import json, os, traceback
with open(os.environ['PUMP_SPLIT_CONFIG']) as f:
    config = json.load(f)
DocumentOpen.Execute(config['input'])
body = list(GetRootPart().GetAllBodies())[0].Master.Shape
result = {'input': config['input'], 'original_volume_mm3': body.Volume*1e9, 'trials': []}
for z in config['z_mm']:
    trial = {'z_mm': z}
    try:
        copy = body.Copy()
        copy.Split(Plane.Create(Frame.Create(Point.Create(0,0,z/1000.0), Direction.DirX, Direction.DirY)), None)
        trial['piece_count'] = copy.PieceCount
        pieces = list(copy.SeparatePieces())
        trial['pieces'] = [{'volume_mm3': p.Volume*1e9, 'faces': len(list(p.Faces)), 'edges': len(list(p.Edges))} for p in pieces]
        trial['relative_volume_error'] = abs(sum(p.Volume for p in pieces)-body.Volume)/body.Volume
    except:
        trial['error'] = traceback.format_exc()
    result['trials'].append(trial)
    with open(config['output'], 'w') as f:
        json.dump(result,f,indent=2)
