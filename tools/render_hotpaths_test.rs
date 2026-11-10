//! Dependency-free checks of the production terrain side sorter.
//! rustc --edition=2024 --test tools/render_hotpaths_test.rs -o target/render-hotpaths-test.exe
//! target/render-hotpaths-test.exe
#![forbid(unsafe_code)]
#![allow(dead_code)]

#[repr(C)]
#[derive(Clone, Copy, Debug)]
pub struct TerrainVertex {
    pub pos: [f32; 3],
    pub uv: [u16; 2],
    pub layer: u16,
    pub light: u16,
    pub color: u32,
}
impl TerrainVertex {
    pub fn new(pos: [f32; 3], uv: [f32; 2], layer: u16, color: u32, light: u16) -> Self {
        Self {
            pos,
            uv: uv.map(|v| (v * 32768.0).round().clamp(0.0, f32::from(u16::MAX)) as u16),
            layer,
            light,
            color,
        }
    }
}

#[path = "../crates/horizon-client/src/mesher/sides.rs"]
mod sides;

#[path = "../crates/horizon-client/src/gfx/binding_cache.rs"]
mod binding_cache;
