/* apriltag_glue.c -- thin C wrapper around the official AprilTag 3 library for WebAssembly.
 *
 * Built by build_apriltag_wasm.py (Docker + Emscripten) together with the pinned
 * AprilRobotics/apriltag sources -> apriltag_wasm.js (single file, wasm inlined as base64).
 *
 * AprilTag itself is (C) 2013-2016 The Regents of The University of Michigan, BSD 2-Clause
 * (https://github.com/AprilRobotics/apriltag/blob/master/LICENSE.md).  This glue file is part of the
 * digital-twin repo and may be used under the same BSD-2-Clause terms.
 *
 * JS API (all pointers are wasm-heap byte offsets):
 *   at_init(nthreads)                            create detector + tag36h11 family; returns 0 on success
 *   at_config(decimate, sigma, refine_edges, decode_sharpening)
 *   at_buffer(w, h)                              (re)allocate the w*h uint8 GRAY input buffer (stride = w);
 *                                                returns its pointer (stable until the next at_buffer call)
 *   at_detect(w, h)                              detect on the buffer; returns the detection count and fills
 *                                                the result array (see at_results)
 *   at_results()                                 pointer to AT_STRIDE doubles per detection:
 *                                                [id, hamming, decision_margin, cx, cy, x0,y0, x1,y1, x2,y2, x3,y3]
 *                                                corners p[0..3] exactly as AprilTag reports them (sub-pixel,
 *                                                image px, y down, wrapping counter-clockwise around the tag)
 *   at_stride()                                  AT_STRIDE (=13)
 *   at_free()                                    release everything
 * Pose estimation (apriltag_pose.c) is deliberately NOT linked in: the AR page solves ONE joint
 * board pose from all tag corners (better conditioned than per-tag pose, and ~20 % smaller wasm).
 */
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include "apriltag.h"
#include "tag36h11.h"
#include "common/image_u8.h"
#include "common/zarray.h"

#define AT_STRIDE 13
#define AT_MAXDET 64

static apriltag_family_t *g_tf = NULL;
static apriltag_detector_t *g_td = NULL;
static uint8_t *g_buf = NULL;
static int g_cap = 0;
static double g_out[AT_MAXDET * AT_STRIDE];

int at_init(int nthreads)
{
    if (g_td) return 0;
    g_tf = tag36h11_create();
    g_td = apriltag_detector_create();
    if (!g_tf || !g_td) return 1;
    apriltag_detector_add_family_bits(g_td, g_tf, 1);   /* accept up to 1 corrected bit; JS gates hamming itself */
    g_td->nthreads = nthreads < 1 ? 1 : nthreads;
    g_td->quad_decimate = 2.0f;
    g_td->quad_sigma = 0.0f;
    g_td->refine_edges = 1;
    g_td->decode_sharpening = 0.25;
    return 0;
}

void at_config(float decimate, float sigma, int refine_edges, double decode_sharpening)
{
    if (!g_td) return;
    g_td->quad_decimate = decimate;
    g_td->quad_sigma = sigma;
    g_td->refine_edges = refine_edges != 0;
    g_td->decode_sharpening = decode_sharpening;
}

uint8_t *at_buffer(int w, int h)
{
    int need = w * h;
    if (need > g_cap) {
        free(g_buf);
        g_buf = (uint8_t *)malloc((size_t)need);
        g_cap = g_buf ? need : 0;
    }
    return g_buf;
}

int at_detect(int w, int h)
{
    if (!g_td || !g_buf || w * h > g_cap) return -1;
    image_u8_t im = { .width = w, .height = h, .stride = w, .buf = g_buf };
    zarray_t *dets = apriltag_detector_detect(g_td, &im);
    int n = zarray_size(dets);
    if (n > AT_MAXDET) n = AT_MAXDET;
    for (int i = 0; i < n; i++) {
        apriltag_detection_t *d;
        zarray_get(dets, i, &d);
        double *o = g_out + i * AT_STRIDE;
        o[0] = d->id; o[1] = d->hamming; o[2] = d->decision_margin;
        o[3] = d->c[0]; o[4] = d->c[1];
        for (int k = 0; k < 4; k++) { o[5 + 2 * k] = d->p[k][0]; o[6 + 2 * k] = d->p[k][1]; }
    }
    apriltag_detections_destroy(dets);
    return n;
}

double *at_results(void) { return g_out; }
int at_stride(void) { return AT_STRIDE; }

void at_free(void)
{
    if (g_td) { apriltag_detector_destroy(g_td); g_td = NULL; }
    if (g_tf) { tag36h11_destroy(g_tf); g_tf = NULL; }
    free(g_buf); g_buf = NULL; g_cap = 0;
}
