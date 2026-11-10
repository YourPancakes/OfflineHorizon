//! CPU grouping microbenchmark: combined Vertex input versus direct particle streams.
//! Inputs are prepared before timing; the producer emits separate streams directly.
//! Compile with rustc -O --edition=2024 -L dependency=target/debug/deps
//! --extern bytemuck=target/debug/deps/libbytemuck-<hash>.rlib
//! --extern wgpu=target/debug/deps/libwgpu-<hash>.rlib
//! tools/particle_batch_bench.rs -o target/particle-batch-bench.exe
#![forbid(unsafe_code)]
#![allow(dead_code)]
use std::{hint::black_box, time::Instant};

#[repr(C)]
#[derive(Clone, Copy, Debug)]
pub struct Vertex {
    pub pos: [f32; 3],
    pub uv: [f32; 2],
    pub layer: u32,
    pub color: u32,
    pub light: u32,
    pub normal: [i8; 4],
    pub glint_uv: [f32; 2],
}

#[path = "../crates/horizon-client/src/gfx/entity_batch.rs"]
mod entity_batch;
#[path = "../crates/horizon-client/src/gfx/particle_batch.rs"]
mod particle_batch;

fn elapsed(mut update: impl FnMut()) -> u128 {
    let start = Instant::now();
    for _ in 0..100 {
        update();
    }
    start.elapsed().as_nanos() / 100
}

fn main() {
    assert_eq!(std::mem::size_of::<Vertex>(), 44);
    for (quads, fraction) in [(1024, 1), (16_384, 1), (65_536, 1), (65_536, 10)] {
        let vertices: Vec<_> = (0..quads * 4)
            .map(|i| Vertex {
                pos: [i as f32 * 0.25, 1.5, -3.0],
                uv: [0.25, 0.75],
                layer: if (i / 4) % fraction == 0 { 15 } else { 0 },
                color: 0xffaabbcc,
                light: 0x00ff00ff,
                normal: [0; 4],
                glint_uv: [0.0; 2],
            })
            .collect();
        let opaque: Vec<_> = vertices.iter().filter(|v| v.layer != 15).copied().collect();
        let particles: Vec<_> = vertices
            .iter()
            .filter(|v| v.layer == 15)
            .map(particle_batch::ParticleVertex::from)
            .collect();
        let mut full = entity_batch::EntityBatch::default();
        let mut compact = entity_batch::EntityBatch::default();
        for _ in 0..40 {
            let expected = full.update(&vertices, &[], &[], &[]);
            let mut actual = compact.update(&opaque, &[], &[], &[]);
            actual[6] += particles.len() as u32 / 4;
            assert_eq!(expected, actual);
        }
        let mut before = Vec::new();
        let mut after = Vec::new();
        for sample in 0usize..11 {
            let mut original = || {
                black_box(full.update(black_box(&vertices), &[], &[], &[]));
                black_box(&full.combined);
            };
            let mut packed = || {
                black_box(compact.update(black_box(&opaque), &[], &[], &[]));
                black_box((&compact.combined, &particles));
            };
            let (a, b) = if sample.is_multiple_of(2) {
                (elapsed(&mut original), elapsed(&mut packed))
            } else {
                let b = elapsed(&mut packed);
                (elapsed(&mut original), b)
            };
            before.push(a);
            after.push(b);
        }
        before.sort_unstable();
        after.sort_unstable();
        let bytes = compact.combined.len() * 44 + particles.len() * 32;
        println!(
            "particle_batch quads={quads} particle_fraction=1/{fraction} original_ns={} direct_ns={} original_bytes={} compact_bytes={bytes}",
            before[5],
            after[5],
            full.combined.len() * 44
        );
    }
}
