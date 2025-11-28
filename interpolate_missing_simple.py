import glob
import csv
import sys
import numpy as np
import os

def load_3d_map(filename):
    """Loads the existing 3D map into a dictionary."""
    data = {}
    if not os.path.exists(filename):
        sys.stderr.write(f"Error: {filename} not found.\n")
        sys.exit(1)
        
    with open(filename, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            idx = int(row['index'])
            # Store as numpy array for easy math
            data[idx] = {
                'pos': np.array([float(row['x']), float(row['y']), float(row['z'])]),
                'norm': np.array([float(row['xn']), float(row['yn']), float(row['zn'])]),
                'error': float(row['error'])
            }
    return data

def scan_2d_files():
    """Scans all 2D files and maps indices to filenames."""
    files = glob.glob("./led_map_2d_*.csv")
    detection_log = {} # {index: [list_of_filenames]}
    
    sys.stderr.write(f"Found {len(files)} 2D detection files.\n")
    
    for fname in files:
        with open(fname, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                idx = int(row['index'])
                if idx not in detection_log:
                    detection_log[idx] = []
                detection_log[idx].append(os.path.basename(fname))
                
    return detection_log

def interpolate_missing(missing_idx, known_data):
    """
    Finds nearest neighbors and linearly interpolates position and normal.
    """
    sorted_known = sorted(known_data.keys())
    
    # Find neighbors
    prev_idx = None
    next_idx = None
    
    # Look for nearest lower neighbor
    for i in range(missing_idx - 1, -1, -1):
        if i in known_data:
            prev_idx = i
            break
            
    # Look for nearest upper neighbor
    max_idx = max(sorted_known)
    for i in range(missing_idx + 1, max_idx + 2):
        if i in known_data:
            next_idx = i
            break
    
    # LOGIC:
    # 1. If we have both neighbors, Lerp (Linear Interpolate)
    # 2. If we only have one (edge of strip), Extrapolate (dangerous) or Clamp.
    #    For safety, we will Clamp (use nearest position) but add a small offset 
    #    so they don't overlap perfectly, or just return None to skip if desired.
    #    Here we will extrapolate using the vector of the nearest 2 neighbors.

    target_pos = np.array([0.0, 0.0, 0.0])
    target_norm = np.array([0.0, 1.0, 0.0])
    
    if prev_idx is not None and next_idx is not None:
        # Standard Interpolation
        # Calculate ratio (alpha)
        total_dist = next_idx - prev_idx
        curr_dist = missing_idx - prev_idx
        alpha = curr_dist / total_dist
        
        p1 = known_data[prev_idx]['pos']
        p2 = known_data[next_idx]['pos']
        
        n1 = known_data[prev_idx]['norm']
        n2 = known_data[next_idx]['norm']
        
        target_pos = (1 - alpha) * p1 + alpha * p2
        target_norm = (1 - alpha) * n1 + alpha * n2
        
    elif prev_idx is not None:
        # End of strip missing, extrapolate from previous two
        p1 = known_data[prev_idx]['pos']
        # Try to find one before that
        prev_prev = prev_idx - 1
        if prev_prev in known_data:
            p0 = known_data[prev_prev]['pos']
            vec = p1 - p0
            target_pos = p1 + (vec * (missing_idx - prev_idx))
            target_norm = known_data[prev_idx]['norm'] # Just copy normal
        else:
            target_pos = p1 # Clamp if only 1 point exists
            target_norm = known_data[prev_idx]['norm']

    elif next_idx is not None:
        # Start of strip missing
        p1 = known_data[next_idx]['pos']
        next_next = next_idx + 1
        if next_next in known_data:
            p2 = known_data[next_next]['pos']
            vec = p1 - p2 # Vector pointing backwards
            target_pos = p1 + (vec * (next_idx - missing_idx))
            target_norm = known_data[next_idx]['norm']
        else:
            target_pos = p1
            target_norm = known_data[next_idx]['norm']

    # Normalize normal vector
    norm_mag = np.linalg.norm(target_norm)
    if norm_mag > 0:
        target_norm = target_norm / norm_mag

    return target_pos, target_norm

def main():
    map_file = "led_map_3d.csv"
    
    # 1. Load Data
    data_3d = load_3d_map(map_file)
    data_2d_log = scan_2d_files()
    
    all_2d_indices = set(data_2d_log.keys())
    existing_3d_indices = set(data_3d.keys())
    
    # 2. Identify Missing
    missing_indices = sorted(list(all_2d_indices - existing_3d_indices))
    
    if not missing_indices:
        sys.stderr.write("No missing indices found! The 3D map is complete relative to 2D files.\n")
        # Proceed to print existing map anyway? User requested "complete 3d csv"
    else:
        sys.stderr.write(f"\n--- MISSING PIXELS REPORT ({len(missing_indices)} total) ---\n")
        sys.stderr.write(f"{'Index':<8} | {'Count':<6} | {'Files (First 3)'}\n")
        sys.stderr.write("-" * 50 + "\n")
        
        for idx in missing_indices:
            files = data_2d_log[idx]
            count = len(files)
            file_summary = ", ".join(files[:3])
            if count > 3: file_summary += "..."
            sys.stderr.write(f"{idx:<8} | {count:<6} | {file_summary}\n")
    
    # 3. Fill Gaps
    sys.stderr.write("\nInterpolating missing points...\n")
    
    final_data = data_3d.copy()
    
    for idx in missing_indices:
        pos, norm = interpolate_missing(idx, final_data) # Pass final_data so we can chain interpolations? 
        # Actually, passing original 'data_3d' is safer to prevent drift errors accumulating, 
        # but passing 'final_data' fills large gaps better. Let's use data_3d for reference to ensure anchor points are real.
        # However, to fill a gap of 5,6,7, we need 5 to calculate 6.
        # BETTER STRATEGY: Do it in passes or simply use the logic in interpolate_missing which searches for NEAREST EXISTING neighbor
        # The logic in `interpolate_missing` searches for nearest EXISTING keys in the dictionary passed.
        # So we update final_data as we go? No, strict linear interp between valid anchors is better.
        
        pos, norm = interpolate_missing(idx, data_3d)
        
        final_data[idx] = {
            'pos': pos,
            'norm': norm,
            'error': -1.0 # Mark as interpolated
        }

    # 4. Output Result
    fieldnames = ['index', 'x', 'y', 'z', 'xn', 'yn', 'zn', 'error']
    writer = csv.DictWriter(sys.stdout, fieldnames=fieldnames)
    writer.writeheader()
    
    for idx in sorted(final_data.keys()):
        entry = final_data[idx]
        writer.writerow({
            'index': idx,
            'x': f"{entry['pos'][0]:.6f}",
            'y': f"{entry['pos'][1]:.6f}",
            'z': f"{entry['pos'][2]:.6f}",
            'xn': f"{entry['norm'][0]:.6f}",
            'yn': f"{entry['norm'][1]:.6f}",
            'zn': f"{entry['norm'][2]:.6f}",
            'error': f"{entry['error']:.6f}"
        })
        
    sys.stderr.write("\nDone. Complete CSV written to stdout.\n")

if __name__ == "__main__":
    main()
