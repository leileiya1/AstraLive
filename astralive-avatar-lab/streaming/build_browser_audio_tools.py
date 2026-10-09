"""Build lab adapters from the production preview sources. No dependency install."""
import pathlib,subprocess
ROOT=pathlib.Path(__file__).parents[2];LAB=ROOT/'astralive-avatar-lab/streaming';ESBUILD=ROOT/'frontend/node_modules/.bin/esbuild'
subprocess.run([str(ESBUILD),str(ROOT/'frontend/src/lib/previewAudioHealth.ts'),'--bundle','--format=iife','--global-name=SoulXAudioHealth','--target=es2022','--outfile='+str(LAB/'browser_audio_health.js')],check=True)
p=LAB/'browser_audio_health.js';p.write_text(p.read_text()+"\nif(typeof module!=='undefined')module.exports=SoulXAudioHealth;\n")
subprocess.run([str(ESBUILD),str(LAB/'cpu_product_preview.tsx'),'--bundle','--format=iife','--define:import.meta.env={}','--target=es2022','--outfile='+str(LAB/'cpu_product_preview.js')],check=True)
