//! GPU format for particle geometry emitted directly with constant normal/glint UV.
use super::Vertex;

pub(super) const ATTRIBUTES: [wgpu::VertexAttribute; 5] =
    wgpu::vertex_attr_array![0=>Float32x3,1=>Float32x2,2=>Uint32,3=>Unorm8x4,4=>Uint8x4];

#[repr(C)]
#[derive(Clone, Copy, Debug, bytemuck::Pod, bytemuck::Zeroable)]
pub struct ParticleVertex {
    pub pos: [f32; 3],
    pub uv: [f32; 2],
    pub layer: u32,
    pub color: u32,
    pub light: u32,
}

impl From<&Vertex> for ParticleVertex {
    fn from(v: &Vertex) -> Self {
        Self {
            pos: v.pos,
            uv: v.uv,
            layer: v.layer,
            color: v.color,
            light: v.light,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn every_variable_attribute_keeps_its_bits() {
        assert_eq!(std::mem::size_of::<ParticleVertex>(), 32);
        let v = Vertex {
            pos: [1.25, -0.3, 13.0],
            uv: [0.15, 0.8],
            layer: 15,
            color: 0xaabbccdd,
            light: 0x12345678,
            normal: [0; 4],
            glint_uv: [0.0; 2],
        };
        let packed = ParticleVertex::from(&v);
        assert_eq!(bytemuck::bytes_of(&packed), &bytemuck::bytes_of(&v)[..32]);
    }
}
