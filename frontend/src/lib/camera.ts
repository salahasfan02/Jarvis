/** Jarvis asking for a camera picture. "Open the camera and tell me what you
 *  see" wants a frame to look at; "take a picture" wants a photo — with a
 *  countdown so the user can pose. App switches to the Camera tab and calls
 *  requestFrame(); the Camera page turns the camera on and answers every
 *  pending request. */

export interface FrameOptions {
  countdown?: number;   // seconds to count down before the shot
  photo?: boolean;      // a photo being kept: flash, and show it afterwards
}

type Waiter = FrameOptions & { resolve: (image: string) => void; reject: (e: Error) => void };

let waiters: Waiter[] = [];
export const cameraBus = new EventTarget();

export function requestFrame(timeoutMs = 15000, opts: FrameOptions = {}): Promise<string> {
  return new Promise((resolve, reject) => {
    const w: Waiter = {
      ...opts,
      resolve: (img) => { clearTimeout(timer); resolve(img); },
      reject: (e) => { clearTimeout(timer); reject(e); },
    };
    const timer = setTimeout(() => {
      waiters = waiters.filter((x) => x !== w);
      reject(new Error("The camera didn't start in time — allow camera access for Jarvis."));
    }, timeoutMs + (opts.countdown ?? 0) * 1000);
    waiters.push(w);
    cameraBus.dispatchEvent(new Event("frame-wanted"));
  });
}

export function framesWanted(): boolean {
  return waiters.length > 0;
}

/** What the pending requests want: the longest countdown, and whether any is
 *  a photo to keep (flash + show it). */
export function pendingShot(): { countdown: number; photo: boolean } {
  return {
    countdown: Math.max(0, ...waiters.map((w) => Math.min(10, Math.max(0, w.countdown ?? 0)))),
    photo: waiters.some((w) => w.photo),
  };
}

/** Hand a photo (or a failure) to everyone waiting. */
export function deliverFrame(image: string | null, error = "") {
  const pending = waiters;
  waiters = [];
  for (const w of pending) {
    if (image) w.resolve(image);
    else w.reject(new Error(error || "Couldn't take a photo."));
  }
}

/** Tell the Camera page its list of photos changed (Jarvis just took one). */
export function photosChanged() {
  cameraBus.dispatchEvent(new Event("photos-changed"));
}
