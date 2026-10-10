#!/usr/bin/env python3
"""Prepare an isolated opt-in Picom13 timing variant. Never installs or launches it."""
import argparse, hashlib, json, pathlib, shutil, tarfile
ROOT=pathlib.Path(__file__).resolve().parents[1]
HEADER=r'''#pragma once
#include <stdint.h>
#include <stdbool.h>
#include <string.h>
bool cd_enabled(void);
/* Preserve IEEE bits, including signed zero and NaNs; never cast double to integer. */
static inline uint64_t cd_double_bits(double value) {
 uint64_t bits; _Static_assert(sizeof(value)==sizeof(bits), "double ABI");
 memcpy(&bits,&value,sizeof(bits)); return bits;
}
void cd_init(void);
void cd_event(uint32_t kind, uint64_t a, uint64_t b, uint64_t c, uint32_t flags);
void cd_render_begin(uint64_t target);
'''
SOURCE=r'''#define _POSIX_C_SOURCE 200809L
#include "carpatic_diag.h"
#include <time.h>
#include <stdlib.h>
#include <stdio.h>
#include <unistd.h>
#include <fcntl.h>
#include <string.h>
#include <sys/stat.h>
#define CAP 65536
struct record { uint64_t sequence, render, monotonic_ns, a, b, c; uint32_t kind, flags, pid, reserved; };
_Static_assert(sizeof(struct record)==64, "record ABI");
static struct record *records;
static uint64_t count, overflow, render_id;
static int output=-1;
static uint32_t process_id;
bool cd_enabled(void) { return records != NULL; }
static void dump(void) {
 if(output<0) return;
 FILE *f=fdopen(output,"w"); if(!f) {close(output); return;}
 fprintf(f,"# carpatic-picom-diag-v1 count=%llu overflow=%llu capacity=%u\n",(unsigned long long)count,(unsigned long long)overflow,CAP);
 fprintf(f,"sequence,render,monotonic_ns,kind,a,b,c,flags,pid\n");
 for(uint64_t i=0;i<count;i++) {struct record *r=&records[i]; fprintf(f,"%llu,%llu,%llu,%u,%llu,%llu,%llu,%u,%u\n",(unsigned long long)r->sequence,(unsigned long long)r->render,(unsigned long long)r->monotonic_ns,r->kind,(unsigned long long)r->a,(unsigned long long)r->b,(unsigned long long)r->c,r->flags,r->pid);}
 fclose(f); output=-1;
}
void cd_init(void) {
 const char *path=getenv("CARPATIC_PICOM_DIAGNOSTIC"); if(!path||path[0]!='/') return;
 output=open(path,O_WRONLY|O_CREAT|O_EXCL|O_NOFOLLOW|O_CLOEXEC,0600); if(output<0) return;
 records=calloc(CAP,sizeof(*records)); if(!records) {close(output);output=-1;return;}
 /* Prefault all pages before any timed render callback. */
 volatile unsigned char *bytes=(volatile unsigned char *)records;
 for(size_t i=0;i<CAP*sizeof(*records);i+=4096) bytes[i]=0;
 process_id=(uint32_t)getpid();
 atexit(dump);
}
void cd_event(uint32_t kind,uint64_t a,uint64_t b,uint64_t c,uint32_t flags) {
 if(!records) return;
 if(count==CAP) {if(overflow!=UINT64_MAX) overflow++;return;}
 struct timespec t; clock_gettime(CLOCK_MONOTONIC,&t);
 records[count]=(struct record){.sequence=count,.render=render_id,.monotonic_ns=(uint64_t)t.tv_sec*1000000000ULL+t.tv_nsec,.kind=kind,.a=a,.b=b,.c=c,.flags=flags,.pid=process_id};
 count++;
}
void cd_render_begin(uint64_t target) {if(records) render_id++;cd_event(2,target,0,0,0);}
'''
def prepare(dest):
 archive=ROOT/'artifacts/render-corruption/picom-v13-src.tar.gz'
 if hashlib.sha256(archive.read_bytes()).hexdigest()!='691ea5b2aa60b8f577ad7af1f5420c2b118594e93c0274677a25faf142c0cd36': raise SystemExit('Pinned archive hash mismatch')
 if dest.exists(): raise SystemExit('Destination must be new; refusing overwrite')
 dest.mkdir(parents=True)
 with tarfile.open(archive) as t: t.extractall(dest,filter='data')
 (dest/'src/carpatic_diag.h').write_text(HEADER)
 (dest/'src/carpatic_diag.c').write_text(SOURCE)
 def patch(file,old,new):
  p=dest/file;s=p.read_text()
  if s.count(old)!=1: raise RuntimeError(f'Hook mismatch {file}: {old[:70]}')
  p.write_text(s.replace(old,new))
 for file in ['src/picom.c','src/vblank.c','src/backend/gl/glx.c','src/backend/xrender/xrender.c','src/wm/win.c']:
  p=dest/file;p.write_text('#include "carpatic_diag.h"\n'+p.read_text())
 patch('src/meson.build',"\t\t'diagnostic.c',","\t\t'diagnostic.c',\n\t\t'carpatic_diag.c',")
 patch('src/picom.c','int PICOM_MAIN(int argc, char **argv) {','int PICOM_MAIN(int argc, char **argv) {\n cd_init();')
 patch('src/picom.c','static void draw_callback_impl(EV_P_ session_t *ps, int revents attr_unused) {','static void draw_callback_impl(EV_P_ session_t *ps, int revents attr_unused) {\n cd_event(1,ps->next_render,ps->backend_busy,ps->redirected,0);')
 patch('src/picom.c','\t\tbool succeeded = renderer_render(','\t\tcd_render_begin(ps->next_render);\n\t\tbool succeeded = renderer_render(')
 patch('src/picom.c','\t\tif (!succeeded) {','\t\tcd_event(3,after_damage_us,0,0,succeeded);\n\t\tif (!succeeded) {')
 patch('src/picom.c','\tif (!completed) {','\tcd_event(10,completed,completed ? (uint64_t)render_time.tv_sec*1000000000ULL+render_time.tv_nsec : 0,0,0);\n\tif (!completed) {')
 patch('src/backend/gl/glx.c','\tglXSwapBuffers(base->c->dpy, gd->target_win);','\tcd_event(4,gd->target_win,0,0,0);\n\tglXSwapBuffers(base->c->dpy, gd->target_win);\n\tcd_event(5,gd->target_win,0,0,0);')
 patch('src/backend/xrender/xrender.c','static bool xrender_present(struct backend_base *base) {\n\tauto xd = (struct xrender_data *)base;','static bool xrender_present(struct backend_base *base) {\n\tauto xd = (struct xrender_data *)base;\n cd_event(6,xd->target_win,0,0,xd->vsync);')
 patch('src/backend/xrender/xrender.c','\t\tauto pcev = (xcb_present_complete_notify_event_t *)pev;','\t\tauto pcev = (xcb_present_complete_notify_event_t *)pev;\n\t\tcd_event(7,pcev->ust,pcev->msc,pcev->kind,((uint32_t)pcev->mode<<8)|1);')
 patch('src/vblank.c','\tbool event_is_invalid = cne->msc <= self->last_msc || cne->ust == 0;','\tbool event_is_invalid = cne->msc <= self->last_msc || cne->ust == 0;\n\tcd_event(8,cne->ust,cne->msc,cne->kind,event_is_invalid);')
 patch('src/vblank.c','\tauto ust = atomic_load(&sched->current_ust);','\tauto ust = atomic_load(&sched->current_ust);\n\tbool cd_synthetic = sched->last_msc >= msc;\n\tcd_event(11,ust,msc-sched->vblank_inserted,sched->vblank_inserted,cd_synthetic);')
 patch('src/vblank.c','\tsched->base.vblank_event_requested = false;\n\tlog_verbose("Received vblank event','\tcd_event(12,ust,sched->last_msc,sched->vblank_inserted,cd_synthetic);\n\tsched->base.vblank_event_requested = false;\n\tlog_verbose("Received vblank event')
 patch('src/vblank.c','\tdouble delay_sec = 0.0;','\tcd_event(9,self->last_ust,self->last_msc,0,event_is_invalid);\n\tdouble delay_sec = 0.0;')
 # Events 20/21 identify the selected script and its output slots. Events
 # 22..24 describe one evaluated sample; flags 0=startup, 1=advance.
 # a is window XID throughout. 20: b=script pointer,c=trigger. 21:
 # b=output enum,c=signed slot encoded uint64,flags=trigger. 22:
 # b=scale-x bits,c=scale-y bits. 23: b=opacity bits,c=offset-x bits.
 # 24: b=offset-y bits,c=script pointer (joins samples to selection).
 # No evaluation, timestamp, allocation or file I/O when disabled.
 patch('src/wm/win.c','#define WSTATE_PAIR(a, b)',r'''static void cd_animation_sample(const struct win *w, uint32_t phase) {
 if (!cd_enabled()) return;
 cd_event(22,win_id(w),cd_double_bits(win_animatable_get(w,WIN_SCRIPT_SCALE_X)),cd_double_bits(win_animatable_get(w,WIN_SCRIPT_SCALE_Y)),phase);
 cd_event(23,win_id(w),cd_double_bits(win_animatable_get(w,WIN_SCRIPT_OPACITY)),cd_double_bits(win_animatable_get(w,WIN_SCRIPT_OFFSET_X)),phase);
 cd_event(24,win_id(w),cd_double_bits(win_animatable_get(w,WIN_SCRIPT_OFFSET_Y)),(uint64_t)(uintptr_t)w->running_animation.script,phase);
}
#define WSTATE_PAIR(a, b)''')
 patch('src/wm/win.c','\t\treturn false;\n\t}\n\treturn true;\n}\n\nbool win_process_animation_and_state_change','\t\tcd_animation_sample(w,1);\n\t\treturn false;\n\t}\n\treturn true;\n}\n\nbool win_process_animation_and_state_change')
 patch('src/wm/win.c','\tw->running_animation = wopts.animations[trigger];','''\tw->running_animation = wopts.animations[trigger];
 if(cd_enabled()) {
  cd_event(20,win_id(w),(uint64_t)(uintptr_t)w->running_animation.script,trigger,0);
  for(size_t i=0;i<ARR_SIZE(w->running_animation.output_indices);i++)
   cd_event(21,win_id(w),i,(uint64_t)(int64_t)w->running_animation.output_indices[i],trigger);
 }''')
 patch('src/wm/win.c','\tscript_instance_evaluate(w->running_animation_instance, &win_ctx, true);','\tscript_instance_evaluate(w->running_animation_instance, &win_ctx, true);\n\tcd_animation_sample(w,0);')
 p=dest/'src/backend/xrender/xrender.c';s=p.read_text();start=s.index('static bool xrender_present(');end=s.index('static int xrender_buffer_age',start);chunk=s[start:end];chunk=chunk.replace('return false;','cd_event(13,0,0,0,xd->vsync);\n\t\t\treturn false;').replace('return true;','cd_event(13,1,0,0,xd->vsync);\n\treturn true;');p.write_text(s[:start]+chunk+s[end:])
 manifest={str(p.relative_to(dest)):hashlib.sha256(p.read_bytes()).hexdigest() for p in dest.rglob('*') if p.is_file()}
 (dest.parent/'source-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
if __name__=='__main__':
 ap=argparse.ArgumentParser();ap.add_argument('--destination',type=pathlib.Path,required=True);args=ap.parse_args();prepare(args.destination.resolve())
