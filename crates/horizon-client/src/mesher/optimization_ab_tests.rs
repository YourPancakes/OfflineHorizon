//! A/B kernels: the original square sums and fresh section buffers are the controls.
use super::*;
use std::{hint::black_box, time::Instant};

fn color(x: i32, z: i32) -> [u32; 3] {
    let hash = (x as u32).wrapping_mul(0x9e37_79b9) ^ (z as u32).wrapping_mul(0x85eb_ca6b);
    [hash & 255, (hash >> 9) & 255, (hash >> 17) & 255]
}

fn old_sum(r: i32, x: i32, z: i32) -> [u32; 3] {
    let mut sum = [0u32; 3];
    for dz in -r..=r {
        for dx in -r..=r {
            let rgb = color(x + dx, z + dz);
            for k in 0..3 {
                sum[k] += rgb[k];
            }
        }
    }
    sum
}

fn rolling_grid(r: i32, order: &[(i32, i32)]) -> Vec<[u32; 3]> {
    let mut sums = [[UNSET; 3]; 256];
    let mut output = Vec::with_capacity(order.len());
    for &(x, z) in order {
        let slot = (z * 16 + x) as usize;
        let px =
            (r > 0 && x > 0 && sums[slot - 1][0] != UNSET).then(|| sums[slot.saturating_sub(1)]);
        let pz =
            (r > 0 && z > 0 && sums[slot - 16][0] != UNSET).then(|| sums[slot.saturating_sub(16)]);
        let sum = tint_window_sum(r, x, z, px, pz, color);
        sums[slot] = sum;
        output.push(sum);
    }
    output
}

#[test]
fn rolling_tints_match_square_reference_for_every_radius_and_order() {
    let forward: Vec<_> = (0..16).flat_map(|z| (0..16).map(move |x| (x, z))).collect();
    let reverse: Vec<_> = forward.iter().copied().rev().collect();
    let scrambled: Vec<_> = (0..256)
        .map(|i| {
            let v = (i * 73) % 256;
            (v % 16, v / 16)
        })
        .collect();
    for radius in 0..=7 {
        for order in [&forward, &reverse, &scrambled] {
            let results = rolling_grid(radius, order);
            for (&(x, z), &actual) in order.iter().zip(&results) {
                let expected = old_sum(radius, x, z);
                assert_eq!(actual, expected, "r={radius}, x={x}, z={z}");
                let n = ((radius * 2 + 1) * (radius * 2 + 1)) as u32;
                let pack = |rgb: [u32; 3]| (rgb[0] / n) << 16 | (rgb[1] / n) << 8 | (rgb[2] / n);
                assert_eq!(pack(actual), pack(expected));
            }
        }
    }
}

fn blank_region() -> Chunk {
    let mut chunk = Chunk::empty(0, 0);
    chunk.set(0, MIN_Y, 0, 1);
    chunk.set(7, MIN_Y + 14, 7, 4);
    chunk
}

#[test]
fn padded_reuse_matches_fresh_buffers_including_missing_neighbors() {
    let center = blank_region();
    let mut neighbor = Chunk::empty(1, 0);
    neighbor.set(0, MIN_Y, 0, 5);
    let mut scratch = MeshScratch::default();
    let mut region = [[None; 3]; 3];
    region[1][1] = Some(&center);
    for sy in [0, 1, 0, 2, 0] {
        region[1][2] = if sy == 0 { Some(&neighbor) } else { None };
        let mut fresh = Padded::new();
        fresh.fill(&region, sy);
        scratch.pad.fill(&region, sy);
        assert_eq!(scratch.pad.blocks, fresh.blocks);
        assert_eq!(scratch.pad.light, fresh.light);
        assert_eq!(scratch.pad.own, fresh.own);
    }
}

#[test]
#[ignore = "A/B microbench; run with --ignored --nocapture"]
fn bench_tint_windows_ab() {
    let order: Vec<_> = (0..16).flat_map(|z| (0..16).map(move |x| (x, z))).collect();
    for radius in [2, 7] {
        let repetitions = 500;
        let start = Instant::now();
        let mut a = 0u32;
        for _ in 0..repetitions {
            for &(x, z) in &order {
                let sum = old_sum(radius, black_box(x), black_box(z));
                a ^= black_box(sum[0]);
            }
        }
        let original = start.elapsed();
        let start = Instant::now();
        let mut b = 0u32;
        for _ in 0..repetitions {
            for sum in rolling_grid(radius, black_box(&order)) {
                b ^= black_box(sum[0]);
            }
        }
        let improved = start.elapsed();
        assert_eq!(a, b);
        println!(
            "tint radius={radius} A={:.3}ms B={:.3}ms speedup={:.2}x",
            original.as_secs_f64() * 1000.0,
            improved.as_secs_f64() * 1000.0,
            original.as_secs_f64() / improved.as_secs_f64()
        );
    }
}

#[test]
#[ignore = "A/B microbench; run with --ignored --nocapture"]
fn bench_padded_reuse_ab() {
    let center = blank_region();
    let mut region = [[None; 3]; 3];
    region[1][1] = Some(&center);
    let repetitions = 500;
    let start = Instant::now();
    let mut a = 0u8;
    for _ in 0..repetitions {
        let mut pad = Padded::new();
        pad.fill(black_box(&region), 0);
        a ^= black_box(pad.light[pi(0, 0, 0)]);
    }
    let original = start.elapsed();
    let start = Instant::now();
    let mut scratch = MeshScratch::default();
    let mut b = 0u8;
    for _ in 0..repetitions {
        scratch.pad.fill(black_box(&region), 0);
        b ^= black_box(scratch.pad.light[pi(0, 0, 0)]);
    }
    let optimized = start.elapsed();
    assert_eq!(a, b);
    println!(
        "padded n={repetitions} A={:.3}ms B={:.3}ms speedup={:.2}x",
        original.as_secs_f64() * 1000.0,
        optimized.as_secs_f64() * 1000.0,
        original.as_secs_f64() / optimized.as_secs_f64()
    );
}
