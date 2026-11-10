// A/B reference: the original light_chunk algorithm, kept for regression tests.
// This is built only under #[cfg(test)] and does not affect the game binary.
use super::*;

fn light_chunk_original(
    region: &[[Option<&Chunk>; 3]; 3],
    tables: &LightTables,
    sky_light: bool,
) -> Vec<Light> {
    region[1][1].expect("centre chunk");
    // Highest occupied section in the region bounds the work.
    let mut top_section = 0;
    for chunk in region.iter().flatten().flatten() {
        for (i, s) in chunk.sections.iter().enumerate().rev() {
            if !s.is_uniform(0) {
                top_section = top_section.max(i + 1);
                break;
            }
        }
    }
    // One extra section above the highest occupied one: block light rises
    // up to 14 blocks into it (sky light there is always 15).
    let h = ((top_section + 1) * 16).min(HEIGHT as usize);
    let at = |x: usize, y: usize, z: usize| (y * W + z) * W + x;
    // Packed cells (`type << 4 | dampening`), not state ids: the flood fill
    // then never touches the large `LightTables::cells` table.
    let mut states = vec![0u16; W * W * h];
    let mut sky = vec![0u8; W * W * h];
    let mut block = vec![0u8; W * W * h];
    let mut queue = VecDeque::new();
    let mut sky_queue = VecDeque::new();
    let mut ids = Box::new([0u32; 4096]);
    for (dz, row) in region.iter().enumerate() {
        for (dx, chunk) in row.iter().enumerate() {
            let Some(chunk) = chunk else { continue };
            for (si, section) in chunk.sections.iter().enumerate().take(top_section) {
                if section.is_uniform(0) {
                    continue;
                }
                section.unpack(&mut ids);
                for (i, &id) in ids.iter().enumerate() {
                    let (lx, lz, ly) = (i & 15, (i >> 4) & 15, i >> 8);
                    let p = at(dx * 16 + lx, si * 16 + ly, dz * 16 + lz);
                    let info = tables.info[id as usize];
                    states[p] = info as u16;
                    let emission = info >> 16;
                    if emission > 0 {
                        block[p] = emission as u8;
                        queue.push_back(p as u32);
                    }
                }
            }
        }
    }
    // Columns of missing neighbour chunks neither hold nor pass light.
    let mut present = vec![false; W * W];
    for z in 0..W {
        for x in 0..W {
            present[z * W + x] = region[z / 16][x / 16].is_some();
        }
    }
    let mut lowest = vec![h as i32; W * W];
    for z in 0..W {
        for x in 0..W {
            if !present[z * W + x] || !sky_light {
                continue;
            }
            // The top layer (above the occupied range) is always open sky.
            let mut y = h as i32 - 1;
            sky[at(x, y as usize, z)] = 15;
            while y > 0
                && !tables.packed_edge_occluded(
                    states[at(x, y as usize, z)],
                    states[at(x, y as usize - 1, z)],
                )
            {
                y -= 1;
                sky[at(x, y as usize, z)] = 15;
            }
            lowest[z * W + x] = y;
        }
    }
    for z in 0..W {
        for x in 0..W {
            if !present[z * W + x] || !sky_light {
                continue;
            }
            let own = lowest[z * W + x];
            let mut deepest = own;
            for (nx, nz) in [
                (x.wrapping_sub(1), z),
                (x + 1, z),
                (x, z.wrapping_sub(1)),
                (x, z + 1),
            ] {
                if nx < W && nz < W && present[nz * W + nx] {
                    deepest = deepest.max(lowest[nz * W + nx]);
                }
            }
            // Seed propagation from the source cells that border darker cells.
            let from = own.max(0) as usize;
            let to = (deepest as usize).min(h - 1);
            for y in from..=to {
                if sky[at(x, y, z)] == 15 {
                    sky_queue.push_back(at(x, y, z) as u32);
                }
            }
        }
    }
    let spread = |light: &mut [u8], queue: &mut VecDeque<u32>| {
        while let Some(p) = queue.pop_front() {
            let p = p as usize;
            let level = light[p];
            if level <= 1 {
                continue;
            }
            let x = p % W;
            let z = (p / W) % W;
            let y = p / (W * W);
            let from = states[p];
            let col = z * W + x;
            // Neighbours by linear offset; `present` only depends on the
            // column, and the axis bounds rule out wrapping.
            macro_rules! neighbour {
                ($d:expr, $q:expr, $ncol:expr) => {{
                    if present[$ncol] {
                        let q = $q;
                        let to = states[q];
                        let next = level.saturating_sub((to & 0xF).max(1) as u8);
                        if next > light[q] && !tables.packed_blocked(from, to, $d) {
                            light[q] = next;
                            queue.push_back(q as u32);
                        }
                    }
                }};
            }
            if y > 0 {
                neighbour!(0, p - W * W, col);
            }
            if y + 1 < h {
                neighbour!(1, p + W * W, col);
            }
            if z > 0 {
                neighbour!(2, p - W, col - W);
            }
            if z + 1 < W {
                neighbour!(3, p + W, col + W);
            }
            if x > 0 {
                neighbour!(4, p - 1, col - 1);
            }
            if x + 1 < W {
                neighbour!(5, p + 1, col + 1);
            }
        }
    };
    spread(&mut sky, &mut sky_queue);
    spread(&mut block, &mut queue);
    pack_lighting(h, &sky, &block, sky_light)
}

fn compare_lights(original: &[Light], reused: &[Light]) {
    assert_eq!(original.len(), reused.len());
    for (section, (a, b)) in original.iter().zip(reused).enumerate() {
        match (a, b) {
            (Light::Uniform(x), Light::Uniform(y)) => assert_eq!(x, y, "section {section}"),
            (Light::Full(x), Light::Full(y)) => {
                assert_eq!(&x[..], &y[..], "section {section}")
            }
            _ => panic!("light representation changed in section {section}"),
        }
    }
}

fn chunks(mode: usize) -> [[Chunk; 3]; 3] {
    let mut region: [[Chunk; 3]; 3] =
        std::array::from_fn(|z| std::array::from_fn(|x| Chunk::empty(x as i32 - 1, z as i32 - 1)));
    if mode == 0 {
        return region;
    }
    for (z, row) in region.iter_mut().enumerate() {
        for (x, chunk) in row.iter_mut().enumerate() {
            let n = (x + z * 3 + mode) as i32;
            let height = match mode % 5 {
                0 => MIN_Y,
                1 => MIN_Y + 15,
                2 => 0,
                3 => 64,
                _ => MIN_Y + HEIGHT - 1,
            };
            // Directional occlusion, block light sources, and both section edges.
            chunk.set((n * 3 + 1) & 15, height, (n * 5 + 1) & 15, TORCH);
            chunk.set(
                (n * 7 + 2) & 15,
                height.saturating_sub(1).max(MIN_Y),
                4,
                SLAB,
            );
            chunk.set((n * 11 + 3) & 15, MIN_Y, 9, STONE);
        }
    }
    region
}

const STONE: u32 = 1;
const TORCH: u32 = 2;
const SLAB: u32 = 3;

fn tables() -> LightTables {
    let cell = |dampening, emission, faces: [u16; 6]| Cell {
        dampening,
        emission,
        shaped: faces.iter().any(|f| *f != EMPTY),
        faces,
    };
    LightTables::from_parts(
        vec![
            cell(0, 0, [EMPTY; 6]),
            cell(15, 0, [FULL; 6]),
            cell(0, 14, [EMPTY; 6]),
            cell(0, 0, [FULL, EMPTY, 2, 2, 2, 2]),
        ],
        vec![false, true, false, true, true, true, false, true, false],
        3,
    )
}

#[test]
fn scratch_matches_original_and_clears_between_jobs() {
    let tables = tables();
    let mut scratch = LightScratch::default();
    let mut cases = 0usize;
    for mode in 0..9 {
        let data = chunks(mode);
        // Centre must remain present; vary missing neighbours and skylight.
        for mask in [0x1ffu16, 0x10, 0x1f, 0x1f0, 0x155, 0x0aa | 0x10] {
            for sky in [false, true] {
                let region: [[Option<&Chunk>; 3]; 3] = std::array::from_fn(|z| {
                    std::array::from_fn(|x| {
                        let i = z * 3 + x;
                        (mask & (1 << i) != 0).then_some(&data[z][x])
                    })
                });
                let a = light_chunk_original(&region, &tables, sky);
                let b = light_chunk_with_scratch(&region, &tables, sky, &mut scratch);
                compare_lights(&a, &b);
                cases += 1;
            }
        }
    }
    assert_eq!(cases, 108);
}

#[test]
fn scratch_output_remains_identical_after_snapshot_changes() {
    let tables = tables();
    let mut scratch = LightScratch::default();
    let mut data = chunks(2);
    for i in 0..20 {
        let x = (i * 7) & 15;
        let z = (i * 11) & 15;
        let y = if i & 1 == 0 { 0 } else { MIN_Y + HEIGHT - 1 };
        data[1][1].set(x, y, z, if i & 1 == 0 { TORCH } else { STONE });
        let region: [[Option<&Chunk>; 3]; 3] =
            std::array::from_fn(|z| std::array::from_fn(|x| Some(&data[z][x])));
        let original = light_chunk_original(&region, &tables, i & 1 == 0);
        let new = light_chunk_with_scratch(&region, &tables, i & 1 == 0, &mut scratch);
        compare_lights(&original, &new);
    }
}

#[test]
fn unusually_large_light_queues_are_not_retained() {
    let tables = tables();
    let data = chunks(0);
    let region: [[Option<&Chunk>; 3]; 3] =
        std::array::from_fn(|z| std::array::from_fn(|x| Some(&data[z][x])));
    let mut scratch = LightScratch::default();
    scratch.queue.reserve(MAX_RETAINED_QUEUE + 1);
    scratch.sky_queue.reserve(MAX_RETAINED_QUEUE + 1);
    assert!(scratch.queue.capacity() > MAX_RETAINED_QUEUE);
    assert!(scratch.sky_queue.capacity() > MAX_RETAINED_QUEUE);
    let a = light_chunk_original(&region, &tables, true);
    let b = light_chunk_with_scratch(&region, &tables, true, &mut scratch);
    compare_lights(&a, &b);
    assert!(scratch.queue.capacity() <= MAX_RETAINED_QUEUE);
    assert!(scratch.sky_queue.capacity() <= MAX_RETAINED_QUEUE);
}

#[test]
#[ignore = "microbenchmark; run with --ignored --nocapture"]
fn benchmark_original_vs_reused_scratch() {
    use std::{hint::black_box, time::Instant};
    let tables = tables();
    for mode in [0, 2, 4] {
        let data = chunks(mode);
        let region: [[Option<&Chunk>; 3]; 3] =
            std::array::from_fn(|z| std::array::from_fn(|x| Some(&data[z][x])));
        let mut scratch = LightScratch::default();
        compare_lights(
            &light_chunk_original(&region, &tables, true),
            &light_chunk_with_scratch(&region, &tables, true, &mut scratch),
        );
        let samples = 30;
        let mut a = Vec::new();
        let mut b = Vec::new();
        for i in 0..11 {
            let first_original = i % 2 == 0;
            for original in [first_original, !first_original] {
                let start = Instant::now();
                for _ in 0..samples {
                    let result = if original {
                        light_chunk_original(black_box(&region), black_box(&tables), true)
                    } else {
                        light_chunk_with_scratch(
                            black_box(&region),
                            black_box(&tables),
                            true,
                            &mut scratch,
                        )
                    };
                    black_box(result);
                }
                let ns = start.elapsed().as_secs_f64() * 1e9 / f64::from(samples);
                if original { a.push(ns) } else { b.push(ns) }
            }
        }
        a.sort_by(f64::total_cmp);
        b.sort_by(f64::total_cmp);
        println!(
            "LIGHT_AB,mode={mode},original_ns={:.1},optimized_ns={:.1},ratio={:.3},reps={samples},pairs=11",
            a[5],
            b[5],
            a[5] / b[5]
        );
    }
}
