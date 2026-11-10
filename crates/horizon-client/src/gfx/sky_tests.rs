//! Pixel comparisons against the original octagon calculation, without game assets.
use super::Globals;
use wgpu::util::DeviceExt;

const BASELINE_DISC: &str = r#"fn disc_distance(d: vec3<f32>, y: f32) -> vec2<f32> {
    if d.y * y <= 0.0 { return vec2(-1.0); }
    let p = d * (y / d.y);
    let h = length(p.xz);
    let phi = atan2(p.z, p.x);
    let sector = PI / 4.0;
    let delta = phi - (floor(phi / sector) * sector + sector * 0.5);
    let edge = 512.0 * cos(sector * 0.5) / cos(delta);
    if h > edge { return vec2(-1.0); }
    let s = h / edge;
    let ay = abs(y);
    let rim = sqrt(512.0 * 512.0 + y * y);
    return vec2(ay + s * (rim - ay), ay + s * (512.0 - ay));
}
"#;

#[test]
fn sky_octagon_matches_original_pixels() {
    compare_sky(false, false);
}

#[test]
#[ignore = "opt-in GPU timing at 1920x1080; requires timestamp queries"]
fn sky_octagon_gpu_timing() {
    compare_sky(true, false);
}

#[test]
#[ignore = "control for GPU timing: both pipelines use the original shader"]
fn sky_gpu_timing_identical_shader_control() {
    compare_sky(true, true);
}

fn compare_sky(timing: bool, identical: bool) {
    let instance = wgpu::Instance::new(wgpu::InstanceDescriptor::new_without_display_handle());
    let Ok(adapter) = pollster::block_on(instance.request_adapter(&Default::default())) else {
        eprintln!("no GPU adapter: skipped sky pixel comparison");
        return;
    };
    eprintln!("sky comparison GPU: {:?}", adapter.get_info());
    let features = if timing {
        assert!(adapter.features().contains(wgpu::Features::TIMESTAMP_QUERY));
        wgpu::Features::TIMESTAMP_QUERY
    } else {
        wgpu::Features::empty()
    };
    let (device, queue) = pollster::block_on(adapter.request_device(&wgpu::DeviceDescriptor {
        required_features: features,
        ..Default::default()
    }))
    .unwrap();
    let current = include_str!("../terrain.wgsl");
    let first = current.find("fn disc_distance(").unwrap();
    let last = current[first..].find("fn sky_fog(").unwrap() + first;
    let reference = format!("{}{}{}", &current[..first], BASELINE_DISC, &current[last..]);
    let modules = [
        reference.as_str(),
        if identical {
            reference.as_str()
        } else {
            current
        },
    ]
    .map(|source| {
        device.create_shader_module(wgpu::ShaderModuleDescriptor {
            label: Some("Sky comparison"),
            source: wgpu::ShaderSource::Wgsl(source.into()),
        })
    });
    let pipelines: Vec<_> = ["fs_sky", "fs_dark_disc"]
        .iter()
        .flat_map(|entry| {
            modules
                .iter()
                .map(|module| {
                    device.create_render_pipeline(&wgpu::RenderPipelineDescriptor {
                        label: Some("Sky comparison"),
                        layout: None,
                        vertex: wgpu::VertexState {
                            module,
                            entry_point: Some("vs_sky"),
                            compilation_options: Default::default(),
                            buffers: &[],
                        },
                        primitive: Default::default(),
                        depth_stencil: None,
                        multisample: Default::default(),
                        fragment: Some(wgpu::FragmentState {
                            module,
                            entry_point: Some(entry),
                            compilation_options: Default::default(),
                            targets: &[Some(wgpu::ColorTargetState {
                                format: wgpu::TextureFormat::Rgba8Unorm,
                                blend: None,
                                write_mask: wgpu::ColorWrites::ALL,
                            })],
                        }),
                        multiview_mask: None,
                        cache: None,
                    })
                })
                .collect::<Vec<_>>()
        })
        .collect();
    let (width, height) = if timing {
        (1920u32, 1080u32)
    } else {
        (128, 96)
    };
    let image_bytes = u64::from(width * height * 4);
    let draws = if timing { 32u32 } else { 1 };
    let timestamps = timing.then(|| {
        let queries = device.create_query_set(&wgpu::QuerySetDescriptor {
            label: Some("Sky benchmark timestamps"),
            ty: wgpu::QueryType::Timestamp,
            count: 4,
        });
        let resolve = device.create_buffer(&wgpu::BufferDescriptor {
            label: None,
            size: 32,
            usage: wgpu::BufferUsages::QUERY_RESOLVE | wgpu::BufferUsages::COPY_SRC,
            mapped_at_creation: false,
        });
        (queries, resolve)
    });
    // Reuse attachments, uniform, bindings and readback as the game does. Both
    // shaders run back-to-back in one submission, before any CPU readback work.
    let uniform = device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
        label: None,
        contents: bytemuck::bytes_of(&<Globals as bytemuck::Zeroable>::zeroed()),
        usage: wgpu::BufferUsages::UNIFORM | wgpu::BufferUsages::COPY_DST,
    });
    let groups: Vec<_> = pipelines
        .iter()
        .map(|pipeline| {
            device.create_bind_group(&wgpu::BindGroupDescriptor {
                label: None,
                layout: &pipeline.get_bind_group_layout(0),
                entries: &[wgpu::BindGroupEntry {
                    binding: 0,
                    resource: uniform.as_entire_binding(),
                }],
            })
        })
        .collect();
    let textures = [0, 1].map(|_| {
        device.create_texture(&wgpu::TextureDescriptor {
            label: None,
            size: wgpu::Extent3d {
                width,
                height,
                depth_or_array_layers: 1,
            },
            mip_level_count: 1,
            sample_count: 1,
            dimension: wgpu::TextureDimension::D2,
            format: wgpu::TextureFormat::Rgba8Unorm,
            usage: wgpu::TextureUsages::RENDER_ATTACHMENT | wgpu::TextureUsages::COPY_SRC,
            view_formats: &[],
        })
    });
    let views = textures
        .each_ref()
        .map(|texture| texture.create_view(&Default::default()));
    let read = device.create_buffer(&wgpu::BufferDescriptor {
        label: None,
        size: image_bytes * 2 + if timing { 32 } else { 0 },
        usage: wgpu::BufferUsages::COPY_DST | wgpu::BufferUsages::MAP_READ,
        mapped_at_creation: false,
    });
    let render_pair = |entry: usize, globals: &Globals, reverse: bool| {
        queue.write_buffer(&uniform, 0, bytemuck::bytes_of(globals));
        let mut encoder = device.create_command_encoder(&Default::default());
        for index in if reverse { [1usize, 0] } else { [0, 1] } {
            let mut pass = encoder.begin_render_pass(&wgpu::RenderPassDescriptor {
                label: None,
                color_attachments: &[Some(wgpu::RenderPassColorAttachment {
                    view: &views[index],
                    depth_slice: None,
                    resolve_target: None,
                    ops: wgpu::Operations {
                        load: wgpu::LoadOp::Clear(wgpu::Color::TRANSPARENT),
                        store: wgpu::StoreOp::Store,
                    },
                })],
                timestamp_writes: timestamps.as_ref().map(|(queries, _)| {
                    wgpu::RenderPassTimestampWrites {
                        query_set: queries,
                        beginning_of_pass_write_index: Some(index as u32 * 2),
                        end_of_pass_write_index: Some(index as u32 * 2 + 1),
                    }
                }),
                ..Default::default()
            });
            let pipeline = entry * 2 + index;
            pass.set_pipeline(&pipelines[pipeline]);
            pass.set_bind_group(0, &groups[pipeline], &[]);
            for _ in 0..draws {
                pass.draw(0..3, 0..1);
            }
        }
        for (index, texture) in textures.iter().enumerate() {
            encoder.copy_texture_to_buffer(
                texture.as_image_copy(),
                wgpu::TexelCopyBufferInfo {
                    buffer: &read,
                    layout: wgpu::TexelCopyBufferLayout {
                        offset: image_bytes * index as u64,
                        bytes_per_row: Some(width * 4),
                        rows_per_image: Some(height),
                    },
                },
                wgpu::Extent3d {
                    width,
                    height,
                    depth_or_array_layers: 1,
                },
            );
        }
        if let Some((queries, resolve)) = &timestamps {
            encoder.resolve_query_set(queries, 0..4, resolve, 0);
            encoder.copy_buffer_to_buffer(resolve, 0, &read, image_bytes * 2, 32);
        }
        queue.submit([encoder.finish()]);
        read.slice(..).map_async(wgpu::MapMode::Read, |_| {});
        device.poll(wgpu::PollType::wait_indefinitely()).unwrap();
        let bytes = read.slice(..).get_mapped_range().unwrap();
        let elapsed = timing.then(|| {
            let stamps: [u64; 4] = bytemuck::pod_read_unaligned(&bytes[image_bytes as usize * 2..]);
            [0usize, 1].map(|index| {
                (stamps[index * 2 + 1] - stamps[index * 2]) as f64
                    * f64::from(queue.get_timestamp_period())
                    / (1_000.0 * f64::from(draws))
            })
        });
        let images = [0usize, 1].map(|index| {
            bytes[image_bytes as usize * index..image_bytes as usize * (index + 1)].to_vec()
        });
        drop(bytes);
        read.unmap();
        (images, elapsed)
    };
    let mut maximum = 0u8;
    let mut different = 0usize;
    let mut timings: [[Vec<f64>; 2]; 2] = std::array::from_fn(|_| Default::default());
    let mut ratios: [Vec<f64>; 2] = Default::default();
    let mut sample = 0usize;
    let fog_ends: &[f32] = if timing {
        &[512.0]
    } else {
        &[32.0, 128.0, 512.0, 1024.0]
    };
    for yaw in [0.0f32, std::f32::consts::FRAC_PI_8, 1.1, 2.8] {
        for pitch in [-1.2f32, -0.1, 0.0, 0.2, 1.2] {
            for alpha in [0.0, 0.6] {
                for &fog_end in fog_ends {
                    let mut globals: Globals = bytemuck::Zeroable::zeroed();
                    globals.view_proj = glam::Mat4::IDENTITY.to_cols_array_2d();
                    globals.inverse_view = (glam::Mat4::from_rotation_y(yaw)
                        * glam::Mat4::from_rotation_x(pitch))
                    .to_cols_array_2d();
                    globals.misc = [0.0, 0.0, width as f32 / height as f32, 0.7002075];
                    globals.fog_ends = [fog_end, 0.0, 0.0, 0.0];
                    globals.fog_color = [0.3, 0.5, 0.7, 1.0];
                    globals.sky_color = [0.4, 0.6, 0.9, 1.0];
                    globals.sunrise = [1.0, 0.4, 0.1, alpha];
                    globals.sun = [0.0, 0.0, yaw.sin(), 0.0];
                    for entry in 0..2 {
                        let (images, elapsed) = render_pair(
                            entry,
                            &globals,
                            !(sample / 2).count_ones().is_multiple_of(2),
                        );
                        if let Some([old, new]) = elapsed
                            && sample >= 4
                        {
                            assert!(old > 0.0 && new > 0.0, "GPU timestamps must advance");
                            timings[entry][0].push(old);
                            timings[entry][1].push(new);
                            ratios[entry].push(new / old);
                        }
                        sample += 1;
                        for (old, new) in images[0].iter().zip(&images[1]) {
                            let delta = old.abs_diff(*new);
                            maximum = maximum.max(delta);
                            different += usize::from(delta != 0);
                        }
                    }
                }
            }
        }
    }
    eprintln!(
        "sky comparison: control={identical} max_channel_error={maximum}/255 differing_channels={different}"
    );
    assert!(maximum <= 1, "sky differs by more than one channel step");
    if timing {
        for (entry, mut times) in timings.into_iter().enumerate() {
            for series in &mut times {
                series.sort_by(f64::total_cmp);
            }
            ratios[entry].sort_by(f64::total_cmp);
            let count = times[0].len();
            eprintln!(
                "sky GPU paired timing control={identical} entry={entry} {width}x{height}, batch={draws}, samples={count}: median original={:.2}us current={:.2}us paired_ratio={:.3}",
                times[0][count / 2],
                times[1][count / 2],
                ratios[entry][count / 2]
            );
        }
    }
}
