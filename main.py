import json
import asyncio
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from playwright.async_api import async_playwright

app = FastAPI()


async def data_extraction(page, roll, home):
    await page.goto(home)
    roll_input = page.locator("input[placeholder='ROLL NO']")
    await roll_input.wait_for(state="visible", timeout=8000)
    await roll_input.fill(str(roll))
    await roll_input.press("Enter")
    await page.wait_for_url(lambda url: url != home, timeout=10000)

    info = await page.evaluate("""() => {
        let a = {};
        for (let i = 0; i < 3; i++) {
            let parts = document
                .getElementsByClassName("table table-bordered")[1]
                .childNodes[1]
                .children[2]
                .querySelector("td")
                .childNodes[2]
                .getElementsByTagName("tr")[i]
                .innerText.split("\\t");
            let key = parts[0].trim().toLowerCase().replace(/ /g, "_").replace(/\\./g, "").replace(/'s/g, "");
            let val = parts[1]?.trim();
            a[key] = val;
        }
        return a;
    }""")

    marks = await page.evaluate("""() => {
        let x = [];
        let rows = document
            .getElementsByClassName("table table-bordered")[1]
            .childNodes[1]
            .children[2]
            .querySelector("td")
            .childNodes[4]
            .getElementsByTagName("tbody")[0]
            .children;
        for (let i = 1; i < rows.length - 1; i++) {
            let data = rows[i].innerText.split("\\t");
            x.push({
                subject: data[0]?.trim(),
                subject_code: data[1]?.trim(),
                credit: data[2]?.trim(),
                grade: data[3]?.trim()
            });
        }
        return x;
    }""")

    result = await page.evaluate("""() => {
        let arr = [];
        for (let i = 0; i < 3; i++) {
            let row = document
                .getElementsByClassName("table table-bordered")[1]
                .childNodes[1]
                .children[2]
                .querySelector("td")
                .childNodes[5]
                .getElementsByTagName("tbody")[0]
                .children[i];
            let parts = row.innerText.split("\\t");
            arr.push({ [parts[0].trim().toLowerCase().replace(/ /g, "_").replace(/\\./g, "")]: parts[1]?.trim() });
        }
        return arr;
    }""")

    return {"roll": roll, "personal_info": info, "marks": marks, "result": result}


async def worker(playwright, rolls, url, queue):
    browser = await playwright.chromium.launch(headless=True)
    page = await browser.new_page()

    for roll in rolls:
        try:
            data = await data_extraction(page, roll, url)
            await queue.put(data)
        except Exception as e:
            await queue.put({"roll": roll, "error": str(e)})

    await browser.close()


async def stream_results(rolls, url):
    first_rolls = []
    second_rolls = []

    for idx, val in enumerate(rolls):
        if idx % 2 == 0:
            first_rolls.append(val)
        else:
            second_rolls.append(val)

    queue = asyncio.Queue()

    async with async_playwright() as p:
        t1 = asyncio.create_task(worker(p, first_rolls, url, queue))
        t2 = asyncio.create_task(worker(p, second_rolls, url, queue))

        remaining = len(rolls)
        while remaining > 0:
            result = await queue.get()
            yield f"data: {json.dumps(result)}\n\n"
            remaining -= 1

        await asyncio.gather(t1, t2)


@app.get("/results/stream")
async def stream_api(rolls: str, url: str):
    rolls = json.loads(rolls)
    return StreamingResponse(
        stream_results(rolls, url),
        media_type="text/event-stream"
    )
