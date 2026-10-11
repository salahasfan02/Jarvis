/** Jarvis asking for a camera photo ("open the camera and tell me what you
 *  see"). App switches to the Camera tab and calls requestFrame(); the
 *  Camera page turns the camera on and answers every pending request. */

type Waiter = { resolve: (image: string) => void; reject: (e: Error) => void };

let waiters: Waiter[] = [];
export const cameraBus = new EventTarget();

export function requestFrame(timeoutMs = 15000): Promise<string> {
  return new Promise((resolve, reject) => {
    const w: Waiter = {
      resolve: (img) => { clearTimeout(timer); resolve(img); },
      reject: (e) => { clearTimeout(timer); reject(e); },
    };
    const timer = setTimeout(() => {
      waiters = waiters.filter((x) => x !== w);
      reject(new Error("The camera didn't start in time — allow camera access for Jarvis."));
    }, timeoutMs);
    waiters.push(w);
    cameraBus.dispatchEvent(new Event("frame-wanted"));
  });
}

export function framesWanted(): boolean {
  return waiters.length > 0;
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
