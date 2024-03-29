# Ordo
Ordo is a Portal which can be used by dental offices for searching products from various dental retailers and ordering products in one place.

- [Project Setup](#project-setup)
- [About Project](#about-project)

## Product Setup
We use `Python 3.8`, if you have different python version, you can use pyenv to install proper Python version.
```shell
git clone git@gitlab.com:zburau/ordo-backend.git
cd ordo-backend
poetry install
poetry shell
pre-commit install
python manage.py migrate
```
Run celery worker & celery beat

```shell
docker run -d -p 6379:6379 redis
celery -A config beat -l INFO --scheduler django_celery_beat.schedulers:DatabaseScheduler
celery -A config worker
```
You can dump database from staging server. I strongly suggest that you can use this data to populate your local database.
To do that please
```bash
cp dump_db.env.example dump_db.env
```
Then fill values for variables in `dump_db.env` and run `./dump_db.sh`

## About Project
Main featurs in Ordo are as followings

- [Onboarding](#onboarding)
- [Order Management](#order-management)
- [About Product](#about-product)
- [Product Search & Suggestion](#product-search--suggestion)
- [Product Price](#product-price)


### Onboarding
**Step 1** - At this very early stage, customer should provide basic user information and company name. Then user will be created and this user is owner of the company

**Step 2** - On this step, the user can create more than one office.

**Step 3** - On this step, the user should set their current month budget for offices. There are 2 types of budget at here. One is `Dental` budget and the other is `Office` budget

**Step 4** - On this step, the user should handle payment, currently this is subscription on sandbox account, so please provide test card number to move forward

**Step 5** - On this step, the user is able to invite another user by email. There are 2 types of user role. `Admin` and `User` , `Admin` has more privileges than `User` role.

**Step 6** - The user can link their dental vendors to their office. As you can see, there are multiple vendors on this page.

We integrated following vendors:
- [Henry Schein](https://www.henryschein.com/)
- [Net 32](https://www.net32.com/)
- [Darby](https://www.darbydental.com/)
- [Patterson](https://www.pattersondental.com/)
- [Ultradent](https://www.ultradent.com/)
- [Benco](https://www.benco.com/)
- [Implant Direct](https://www.implantdirect.com/)
- [Edge Endo](https://www.edgeendo.com/)
- [Dental City](https://dentalcity.com/)

**What does linking mean exactly?**

The user should share credentials of each vendor with us. Let’s assume that the user has an account on Henry Schein and they want to link it to our platform. They should input `username`, `password` of Henry Schein on the modal. If they click Link button, we validates if they provide correct username & password. If they provide correct credentials, we start a background task to fetch order made within last 12 months.



### Order Management
Our customers can add products to the cart and checkout the order. But real orders are not made on our platform, They will be made on vendors side.

Lets say user add 2 products to our cart. one from `Henry Schein`, the other from `Net 32`. If the user check out, our platform will create an order on `Henry Schein` on behalf of this user. Also our platform will create an order on `Net 32` on behalf of this user.

**Is it possible for us to create an order on behalf of customer?**

Yes. They share the account credentials of vendors with us. By using these credentials, we could add products to Vendor’s cart, checkout. Technically we create a logged-in session using Python `requests` library, do all necessary things that are required.

**What if the user place an order on Vendor site directly.**

Good question. We have a background task that can be used to sync with vendor side. If the user place an order without using our platform, we fetch them.


### About Product
We have scrapers(written in Python and Scrapy) for fetching all products from Dental Vendor sites. We imported products into our database. One important field in `Product` model is `manufacturer_number`. This is the number dubbed by manufacturing company. For example, take a look at following products on their websites.

- [Septocaine Product from Henry Schein](https://www.henryschein.com/us-en/dental/p/anesthetics/injectables/septocaine-4-w-epi-1-7-ml-inj/2280944)
- [Septocaine Product from Net 32](https://www.net32.com/ec/septocaine-articaine-hcl-4-epinephrine-1200000-50-d-76280)

You can easily understand that those 2 products are exactly same products. Those products are manufactured by same company but is being sold on different vendors at different prices. Search for `01A1200`, this is the manufacturer number. On our side, we should display that kind of products as a single product on our website like below screenshot.

So there is a product called **Septocaine® Articaine HCl 4% and Epinephrine 1:200,000 Silver Box of 50,** the user can buy this product from

- Henry Schein at $44.80
- Dental City at $57.99
- Net 32 at $58.50
- etc

Each product has the following information:

- **product_id**: This is vendor-specific product id. Product ID number of each vendor
- **price**: This is the price of the product, but this is not constant. This value will be null for `Formula vendors`, I will explain what `Formula Vendor` is later.
- **sku**, **description** and so on: As the name suggest, you can guess what it is


### Product Search & Suggestion
We have over 500k products in the `products` table. In order to implement search, we use Postgresql Full-Text Search.

**Product Suggestion**: If the user search products in Search bar, on the frontend side, it calls suggestion api. You can check endpoint on Browser Inspect Tool. The corresponding backend code is `get_product_suggestion` function in `apps/orders/views/ProductV2ViewSet`

**Product Search**: Once the user click the search icon, far right in Search bar, it calls product search api. You can check endpoint oin Browser Inspect Tool. The corresponding backend code is `list` function in `apps/orders/views/ProductV2ViewSet`

### Product Price
Product Price is not constant. It changes as the time wear on. And some vendors apply different pricing policy toward their customers. We call these vendors formula vendors.

Formula vendors are `Henry Schein`, `Darby`, `Patterson`, `Benco`

Non-formula vendors are `Net 32`, `Dental City`, `Implant Direct`, `Edge Endo`

**What does Formula vendor mean exactly?**

Lets say

- `Dental Hospital A` creates an account on Henry Schein.
- `Dental Hospital B` creates an account on Henry Schein.

`Henry Schein` sell the same product at different price to Dental hospitals, for example,

- They charge $40 for `product A` to `Dental Hospital A`
- They charge $50 for `product A` to `Dental Hospital B`

That is why we have another `price` field in `OfficeProduct` model

**How about Non-formula vendors? The prices are constant**
No. they sell products at same prices to customers. But the price of products changes as the time goes on. That is why we fetch the price of products on-the-fly every 2 weeks.
